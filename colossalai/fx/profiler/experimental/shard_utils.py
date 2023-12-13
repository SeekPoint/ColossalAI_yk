# for PyTorch 1.11 compatibility uses

from torch.fx import Node

from ..._compatibility import compatibility
from pydebug import gd, infoTensor
__all__ = ["calculate_fwd_in", "calculate_fwd_tmp", "calculate_fwd_out"]


@compatibility(is_backward_compatible=True)
def calculate_fwd_in(n: Node) -> bool:
    """A helper function to calculate `fwd_in`

    Args:
        n (Node): a node from the graph

    Returns:
        save_fwd_in (bool): the result of `save_fwd_in`
    """
    gd.debuginfo(prj="mt", info=f'')
    return n.meta["save_fwd_in"]


@compatibility(is_backward_compatible=True)
def calculate_fwd_tmp(n: Node) -> int:
    """A helper function to calculate `fwd_tmp`

    Args:
        n (Node): a node from the graph

    Returns:
        fwd_tmp (int): the result of `fwd_tmp`
    """
    gd.debuginfo(prj="mt", info=f'')
    return n.meta["fwd_mem_tmp"]


@compatibility(is_backward_compatible=True)
def calculate_fwd_out(n: Node) -> int:
    """A helper function to calculate `fwd_out`

    Args:
        n (Node): a node from the graph

    Returns:
        fwd_out (int): the result of `fwd_out`
    """
    gd.debuginfo(prj="mt", info=f'')
    return n.meta["fwd_mem_out"]
