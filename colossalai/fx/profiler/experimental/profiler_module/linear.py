from typing import Tuple

import torch
from pydebug import gd, infoTensor
from ..registry import meta_profiler_module


@meta_profiler_module.register(torch.nn.Linear)
@meta_profiler_module.register(torch.nn.modules.linear.NonDynamicallyQuantizableLinear)
def torch_nn_linear(self: torch.nn.Linear, input: torch.Tensor) -> Tuple[int, int]:
    gd.debuginfo(prj="mt", info=f'')
    out_features = self.weight.shape[0]
    macs = input.numel() * out_features
    flops = 2 * macs
    if self.bias is not None:
        flops += self.bias.numel()
        gd.debuginfo(prj="mt", info=f'')
    return flops, macs
