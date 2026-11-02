"""Standard-library metric model; does not emulate autograd or an optimizer."""
import json


def reported_loss(token_losses, valid_mask):
    numerator = sum(token_losses)
    denominator = sum(valid_mask)
    return numerator / denominator


def workload():
    for step, mask in ((41, [1, 1, 1, 1]), (42, [1, 0, 0, 0])):
        losses = [2.0, 2.0, 2.0, 2.0]
        yield {"job": "fixture", "rank": 0, "step": step,
               "token_losses": losses, "valid_mask": mask,
               "reported_loss": reported_loss(losses, mask), "grad_norm": 3.0}


if __name__ == "__main__":
    for record in workload():
        print(json.dumps(record, sort_keys=True, allow_nan=False))
