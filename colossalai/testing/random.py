import random

import numpy as np
import torch
from pydebug import gd, infoTensor

def seed_all(seed, cuda_deterministic=False):
    gd.debuginfo(prj="mt", info=f'')
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
        gd.debuginfo(prj="mt", info=f'')
    if cuda_deterministic:  # slower, more reproducible
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False
        gd.debuginfo(prj="mt", info=f'')
    else:
        torch.backends.cudnn.deterministic = False
        torch.backends.cudnn.benchmark = True
        gd.debuginfo(prj="mt", info=f'')
