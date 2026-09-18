"""Behavioral checks: ordered records, explicit stack mapping, safe alignment and all ranks."""
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import msprobe as m


def tensor(norm=1, shape=None, dtype="torch.float32", **extra):
    return {"type": "torch.Tensor", "dtype": dtype, "shape": [2] if shape is None else shape,
            "Norm": norm, "Max": norm, "Min": 0, "Mean": norm/2, **extra}


def operation(norm=1, shape=None, dtype="torch.float32", recompute=False):
    return {"input_args": [tensor(1, shape, dtype)], "input_kwargs": {},
            "output": [tensor(norm, shape, dtype)], "is_recompute": recompute}


def frame(code="return layer(x)", line=7, root="/model"):
    return f"File {root}/net.py, line {line}, in forward, \n {code}"


def dump(data, stacks=None):
    stacks = stacks if stacks is not None else {"opaque": [list(data), [frame()]]}
    return m.Dump({"data": data}, stacks, {"dump": "fixture/dump.json", "step": "2", "rank": "0"})


class ReaderTests(unittest.TestCase):
    def test_execution_order_not_numeric_api_order_and_stack_ids_are_opaque(self):
        data = {"Functional.linear.10.forward": operation(), "Functional.linear.2.forward": operation(recompute=True),
                "Functional.linear.10.backward": {"input": [tensor()], "output": [tensor()]}}
        stacks = {"999": [["Functional.linear.10.forward"], [frame("return first(x)")]],
                  "3": [["Functional.linear.2.forward"], [frame("return second(x)")]]}
        d = dump(data, stacks)
        self.assertEqual([r["api"] for r in d.records], list(data))
        self.assertEqual(d.inspect("Functional.linear.10.forward")["stack_group"], "999")
        backward = d.inspect("Functional.linear.10.backward")
        self.assertEqual(backward["stack_api"], "Functional.linear.10.forward")
        self.assertIn("first(x)", backward["frames"][0])
        self.assertTrue(d.records[1]["is_recompute"])

    def test_stack_group_can_name_multiple_apis(self):
        d = dump({"Tensor.mul.7.forward": operation(), "Tensor.add.8.forward": operation()})
        self.assertEqual(d.records[0]["frames"], d.records[1]["frames"])
        with self.assertRaisesRegex(ValueError, "conflicting"):
            m.stack_index({"x": [["A"], [frame()]], "y": [["A"], [frame("other(x)")]]})

    def test_renumbered_calls_align_by_stack_shape_and_dtype_difference_survives(self):
        left = dump({"Functional.linear.9.forward": operation(3)})
        right = dump({"Functional.linear.123.forward": operation(4, dtype="torch.bfloat16")},
                     {"17": [["Functional.linear.123.forward"], [frame(line=99)]]})
        pair = list(m.align(left, right))[0]
        self.assertEqual(pair["status"], "matched")
        result = m.compare_records(pair["left"], pair["right"])
        self.assertTrue(any(c["path"].endswith("/dtype") for c in result["changes"]))
        norm = next(c for c in result["changes"] if c["path"] == "/output/0/Norm")
        self.assertEqual(norm["absolute_difference"], 1)
        self.assertEqual(norm["ratio_to_right"], .75)

    def test_same_name_different_stack_or_shape_is_not_a_match(self):
        api = "Functional.linear.0.forward"
        left = dump({api: operation()})
        for right in (dump({api: operation(shape=[3])}),
                      dump({api: operation()}, {"0": [[api], [frame("return other(x)")]]})):
            pairs = list(m.align(left, right))
            self.assertEqual([p["status"] for p in pairs], ["left_only", "right_only"])

    def test_repeats_use_execution_occurrence_but_unequal_counts_remain_ambiguous(self):
        a = dump({"Tensor.mul.9.forward": operation(2), "Tensor.mul.1.forward": operation(3)})
        b = dump({"Tensor.mul.30.forward": operation(2), "Tensor.mul.20.forward": operation(3)})
        pairs = list(m.align(a, b))
        self.assertEqual([p["right"]["api"] for p in pairs], list(b.data))
        self.assertEqual([p["occurrence"] for p in pairs], [0, 1])
        b = dump({"Tensor.mul.30.forward": operation()})
        self.assertFalse(any(p["status"] == "matched" for p in m.align(a, b)))
        self.assertEqual(next(m.align(a, b))["status"], "ambiguous")

    def test_missing_stack_does_not_fall_back_to_same_api_name(self):
        a = dump({"Tensor.mul.0.forward": operation()}, {})
        b = dump({"Tensor.mul.0.forward": operation()})
        self.assertEqual(next(m.align(a, b))["reason"], "missing_stack")

    def test_backward_extra_ports_are_explicit_not_silent_misalignment(self):
        forward = "Functional.linear.0.forward"
        backward = "Functional.linear.0.backward"
        a = dump({forward: operation(), backward: {"input": [tensor(2), None], "output": [tensor(3), None]}})
        b = dump({forward: operation(), backward: {"input": [tensor(4)], "output": [tensor(5)]}})
        pair = list(m.align(a, b))[1]
        self.assertEqual(pair["status"], "matched")
        result = m.compare_records(pair["left"], pair["right"])
        self.assertTrue(result["role_check_required"])
        self.assertTrue(any(c["path"] == "/input/0/Norm" for c in result["changes"]))

    def test_dtensor_view_and_nested_statistics_are_preserved(self):
        value = {"type": "torch.distributed.tensor.DTensor", "device_mesh": [0, 1],
                 "placements": [{"Shard": {"dim": 0}}], "local_tensor": tensor(3)}
        item = list(m.tensor_fields([[value]], "/input_args"))[0]
        self.assertEqual(item["path"], "/input_args/0/0/local_tensor")
        self.assertEqual(item["distribution"]["view"], "DTensor_local_record")
        self.assertEqual(item["distribution"]["device_mesh"], [0, 1])
        self.assertEqual(item["shape"], [2])
        self.assertEqual(item["statistics"]["Norm"], 3)  # No multiplication by mesh size.

    def test_nonfinite_missing_zero_and_small_differences_are_not_hidden(self):
        for a, b in ((float("nan"), float("nan")), ("NaN", "NaN"), (float("inf"), 1)):
            self.assertEqual(m.difference(a, b)["status"], "nonfinite")
        self.assertEqual(m.difference(None, None)["status"], "unavailable")
        self.assertIsNone(m.difference(0, 0))
        self.assertEqual(m.difference(1e-14, 0)["status"], "different")
        self.assertIsNone(m.difference(1e-14, 0)["ratio_to_right"])
        self.assertNotIn('NaN,', m.encode({"x": float("nan")}))

    def test_stack_normalization_preserves_call_identity_and_raw_frame(self):
        a = 'File /home/a/site-packages/torch/op.py, line 10, in f, \n return run(x)'
        b = 'File /usr/lib/dist-packages/torch/op.py, line 30, in f, \n return run(x)'
        self.assertEqual(m.normalize_frame(a), m.normalize_frame(b))
        self.assertNotEqual(m.normalize_frame(a), m.normalize_frame(b.replace('run(x)', 'run(y)')))
        self.assertEqual(m.normalize_frame(frame(root='/left'), '/left'), m.normalize_frame(frame(root='/right'), '/right'))

    def test_boundary_evidence_separates_input_and_output_without_equality_claim(self):
        a, b = dump({'Tensor.mul.0.forward': operation(100)}), dump({'Tensor.mul.9.forward': operation(1)})
        pair = next(m.align(a, b))
        result = m.boundary_evidence(pair['left'], pair['right'], m.compare_records(pair['left'], pair['right']))
        self.assertEqual(result['input']['statistics']['equal'], 4)
        self.assertEqual(result['input']['statistics']['different'], 0)
        self.assertEqual(result['output']['largest_norm_absolute']['absolute_difference'], 99)
        self.assertEqual(result['output']['largest_norm_relative']['path'], '/output/0/Norm')
        self.assertNotIn('root_cause', result)

    def test_boundary_evidence_keeps_nonfinite_missing_zero_and_metadata(self):
        a, b = operation(1e-14), operation(0)
        a['input_kwargs']['mask'] = {**tensor(dtype='torch.bool'), 'Norm': None, 'Mean': None, 'Max': True, 'Min': False}
        b['input_kwargs']['mask'] = tensor(float('inf'))
        a['input_args'][0]['Norm'] = float('nan')
        da, db = dump({'Tensor.mul.0.forward': a}), dump({'Tensor.mul.0.forward': b})
        pair = next(m.align(da, db))
        result = m.boundary_evidence(pair['left'], pair['right'], m.compare_records(pair['left'], pair['right']))
        self.assertGreater(result['input']['statistics']['nonfinite'], 0)
        self.assertGreater(result['input']['statistics']['unavailable'], 0)
        self.assertEqual(result['output']['largest_norm_absolute']['left'], 1e-14)
        self.assertIsNone(result['output']['largest_norm_absolute']['relative_to_right'])
        self.assertTrue(any(c['path'].endswith('/mask/dtype') for c in result['metadata_changes']))

    def test_root_output_tensor_stays_in_output_group(self):
        a, b = operation(), operation()
        a['output'], b['output'] = tensor(100), tensor(1)
        pair = next(m.align(dump({'Tensor.mul.0.forward': a}), dump({'Tensor.mul.0.forward': b})))
        result = m.boundary_evidence(pair['left'], pair['right'], m.compare_records(pair['left'], pair['right']))
        self.assertEqual(result['input']['paired_ports'], 1)
        self.assertEqual(result['input']['statistics']['different'], 0)
        self.assertEqual(result['output']['paired_ports'], 1)
        self.assertEqual(result['output']['statistics']['different'], 3)
        self.assertEqual(result['output']['largest_norm_absolute']['path'], '/output/Norm')


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write_rank(self, side, rank, norm=1, mesh=None):
        folder = self.root / side / 'step2' / f'rank{rank}'
        folder.mkdir(parents=True)
        op = operation(norm)
        if mesh:
            op['output'][0].update(type='torch.distributed.tensor.DTensor', device_mesh=mesh,
                                   placements=[{'Shard': {'dim': 0}}])
        data = {'Tensor.mul.7.forward': op}
        (folder/'dump.json').write_text(json.dumps({'data': data}), encoding='utf-8')
        (folder/'stack.json').write_text(json.dumps({'999': [list(data), [frame()]]}), encoding='utf-8')
        return folder

    def test_query_pages_each_rank_without_source_access_and_retains_empty_ranks(self):
        for side in ('left', 'right'):
            for rank in (0, 7):
                folder = self.write_rank(side, rank, norm=100 if side == 'left' and rank == 7 else 1)
                data = json.loads((folder/'dump.json').read_text(encoding='utf-8'))['data']
                data['Tensor.mul.8.forward'] = operation(2)
                data['Tensor.mul.9.forward'] = operation(3, recompute=True)
                (folder/'dump.json').write_text(json.dumps({'data': data}), encoding='utf-8')
                (folder/'stack.json').write_text(json.dumps({'g': [list(data), [frame()]]}), encoding='utf-8')
            self.write_rank(side, 9)
        with m.Source(self.root/'left') as a, m.Source(self.root/'right') as b:
            m.scan(a, b, self.root/'out')
        with patch.object(m, 'Source', side_effect=AssertionError('query must not reopen sources')):
            result = m.query_scan(self.root/'out', api='Tensor.mul.*', phase='forward', limit=1)
        self.assertEqual([r['rank'] for r in result['ranks']], ['0', '7', '9'])
        self.assertEqual([r['match_count'] for r in result['ranks']], [2, 2, 1])
        self.assertEqual([r['next_offset'] for r in result['ranks']], [1, 1, None])
        seven = result['ranks'][1]['rows'][0]
        self.assertEqual(seven['boundary_evidence']['output']['largest_norm_absolute']['absolute_difference'], 99)
        second = m.query_scan(self.root/'out', phase='forward', limit=1, offset=1)
        self.assertEqual(second['ranks'][1]['rows'][0]['left']['api'], 'Tensor.mul.8.forward')
        self.assertEqual(second['ranks'][2]['rows'], [])
        recompute = m.query_scan(self.root/'out', phase='recompute')
        self.assertEqual([r['match_count'] for r in recompute['ranks']], [1, 1, 0])
        self.assertEqual(recompute['ranks'][2]['rows'], [])
        self.assertTrue(recompute['ranks'][0]['sources']['left']['dump_sha256'])

    def test_query_retains_missing_rank_and_legacy_scan_limits(self):
        self.write_rank('left', 0)
        self.write_rank('right', 0)
        self.write_rank('left', 7)
        with m.Source(self.root/'left') as a, m.Source(self.root/'right') as b:
            m.scan(a, b, self.root/'out')
        path = self.root/'out/alignment.jsonl'
        rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
        for row in rows:
            row.pop('boundary_evidence', None)
        path.write_text(''.join(json.dumps(r)+'\n' for r in rows), encoding='utf-8')
        result = m.query_scan(self.root/'out')
        self.assertFalse(result['scan_coverage']['coverage_complete'])
        self.assertEqual(result['ranks'][0]['matched_rows_without_boundary_evidence'], 1)
        self.assertEqual(result['ranks'][1]['rows'][0]['reason'], 'peer_rank_missing')
        with self.assertRaises(ValueError):
            m.query_scan(self.root/'out', rank='99')
        for options in ({'limit': 0}, {'offset': -1}):
            with self.assertRaises(ValueError):
                m.query_scan(self.root/'out', **options)

    def test_query_cli_matches_right_api_and_preserves_backward_role_warning(self):
        for side, index in (('left', 2), ('right', 90)):
            folder = self.write_rank(side, 0)
            fwd, bwd = f'Functional.linear.{index}.forward', f'Functional.linear.{index}.backward'
            output = [tensor(5)] if side == 'left' else [tensor(6), tensor(7)]
            data = {fwd: operation(), bwd: {'input': [tensor()], 'output': output}}
            (folder/'dump.json').write_text(json.dumps({'data': data}), encoding='utf-8')
            (folder/'stack.json').write_text(json.dumps({'g': [[fwd], [frame()]]}), encoding='utf-8')
        with m.Source(self.root/'left') as a, m.Source(self.root/'right') as b:
            m.scan(a, b, self.root/'out')
        result = subprocess.run([sys.executable, str(Path(m.__file__)), 'query', '--scan', str(self.root/'out'),
            '--api', 'Functional.linear.90.*', '--phase', 'backward'], capture_output=True, encoding='utf-8', check=True)
        row = json.loads(result.stdout)['ranks'][0]['rows'][0]
        self.assertEqual(row['left']['api'], 'Functional.linear.2.backward')
        self.assertTrue(row['role_check_required'])
        self.assertEqual(row['boundary_evidence']['output']['unpaired_ports'], 1)

    def test_query_rejects_truncated_cache_even_with_valid_json_lines(self):
        for side in ('left', 'right'):
            for rank in (0, 7):
                self.write_rank(side, rank)
        with m.Source(self.root/'left') as a, m.Source(self.root/'right') as b:
            m.scan(a, b, self.root/'out')
        path = self.root/'out/alignment.jsonl'
        first = path.read_text(encoding='utf-8').splitlines()[0]
        path.write_text(first+'\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'incomplete or inconsistent'):
            m.query_scan(self.root/'out', rank='0')

    def test_scan_reads_nonzero_rank_and_keeps_unmatched_rank(self):
        for side in ('left', 'right'):
            self.write_rank(side, 0)
            self.write_rank(side, 7, norm=100 if side == 'left' else 1)
        self.write_rank('left', 8)
        with m.Source(self.root/'left') as a, m.Source(self.root/'right') as b:
            result = m.scan(a, b, self.root/'out')
        self.assertEqual(len(result['ranks']), 3)
        self.assertEqual(result['missing_rank_pairs'], [['2', '8']])
        seven = next(r for r in result['ranks'] if r['rank'] == '7')
        self.assertEqual(seven['largest_norm_differences']['forward'][0]['absolute_difference'], 99)
        self.assertFalse(result['coverage_complete'])
        rows = [json.loads(line) for line in (self.root/'out/alignment.jsonl').read_text(encoding='utf-8').splitlines()]
        missing = [row for row in rows if row['rank'] == '8']
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0]['reason'], 'peer_rank_missing')
        self.assertEqual(missing[0]['left']['api'], 'Tensor.mul.7.forward')

    def test_mesh_missing_on_both_sides_is_reported(self):
        for side in ('left', 'right'):
            self.write_rank(side, 0, mesh=[0, 1])
        with m.Source(self.root/'left') as a, m.Source(self.root/'right') as b:
            result = m.scan(a, b, self.root/'out')
        self.assertEqual(result['missing_mesh_ranks'], {'left': {'2': ['1']}, 'right': {'2': ['1']}})
        self.assertFalse(result['coverage_complete'])

    def test_tar_and_zip_are_read_without_extraction_and_cli_inspect_works(self):
        folder = self.write_rank('input', 0)
        tar_path, zip_path = self.root/'a.tgz', self.root/'a.zip'
        with tarfile.open(tar_path, 'w:gz') as archive:
            for path in folder.iterdir():
                data = path.read_bytes()
                member = tarfile.TarInfo('./step2/rank0/' + path.name)
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
        with zipfile.ZipFile(zip_path, 'w') as archive:
            for path in folder.iterdir():
                archive.writestr('step2/rank0/' + path.name, path.read_bytes())
        with m.Source(tar_path) as a, m.Source(zip_path) as b:
            self.assertEqual(a.load(('2','0')).keys, b.load(('2','0')).keys)
            self.assertIn('!./step2/rank0/', a.load(('2','0')).source['dump'])
        result = subprocess.run([sys.executable, str(Path(m.__file__)), 'inspect', '--data', str(tar_path),
                                 '--rank', '0', '--api', 'Tensor.mul.7.forward'], capture_output=True, encoding='utf-8', check=True)
        self.assertEqual(json.loads(result.stdout)['stack_group'], '999')
        self.assertFalse((self.root/'step2').exists())

    def test_read_error_is_not_complete_coverage(self):
        for side in ('left', 'right'):
            self.write_rank(side, 0)
            folder = self.write_rank(side, 1)
            if side == 'left':
                (folder/'dump.json').write_text('{"data":[]}', encoding='utf-8')
        with m.Source(self.root/'left') as a, m.Source(self.root/'right') as b:
            result = m.scan(a, b, self.root/'out')
        self.assertFalse(result['all_available_shards_read'])
        self.assertEqual(len(result['errors']), 1)
        self.assertEqual(result['ranks'][0]['counts']['matched'], 1)
        rows = [json.loads(line) for line in (self.root/'out/alignment.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertTrue(any(row.get('reason') == 'peer_rank_unreadable' for row in rows))

    def test_shape_match_without_statistics_is_not_a_precision_comparison(self):
        for side in ('left', 'right'):
            folder = self.write_rank(side, 0)
            path = folder/'dump.json'
            data = json.loads(path.read_text(encoding='utf-8'))
            for field in ('input_args', 'output'):
                for key in m.STATS:
                    data['data']['Tensor.mul.7.forward'][field][0].pop(key)
            path.write_text(json.dumps(data), encoding='utf-8')
        with m.Source(self.root/'left') as a, m.Source(self.root/'right') as b:
            result = m.scan(a, b, self.root/'out')
        self.assertEqual(result['ranks'][0]['counts']['matched'], 1)
        quality = result['ranks'][0]['comparison']
        self.assertEqual(quality['statistic_fields_compared'], 0)
        self.assertEqual(quality['records_without_statistic_comparison'], 1)
        self.assertEqual(quality['unavailable_fields'], 8)


if __name__ == '__main__':
    unittest.main(verbosity=2)
