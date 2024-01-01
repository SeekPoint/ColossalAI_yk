import argparse
import math
import warnings
import sys
sys.path.append('./')
import os
import torch
import torch.distributed as dist
from coati.dataset import SFTDataset, SupervisedDataset
from coati.models.bloom import BLOOMActor
from coati.models.chatglm import ChatGLMActor
from coati.models.chatglm.chatglm_tokenizer import ChatGLMTokenizer
from coati.models.gpt import GPTActor
from coati.models.llama import LlamaActor
from coati.models.opt import OPTActor
from coati.trainer import SFTTrainer
from coati.trainer.strategies import DDPStrategy, GeminiStrategy, LowLevelZeroStrategy
from datasets import load_dataset
from torch.optim import Adam
from torch.utils.data import DataLoader
from torch.utils.data.distributed import DistributedSampler
from transformers import AutoTokenizer, BloomTokenizerFast, LlamaTokenizer
from transformers.models.gpt2.tokenization_gpt2 import GPT2Tokenizer
from transformers.trainer import get_scheduler

from colossalai.logging import get_dist_logger
from colossalai.nn.optimizer import HybridAdam
from pydebug import gd, infoTensor

def train(args):
    gd.debuginfo(prj="mt")
    # configure strategy
    if args.strategy == "ddp":
        strategy = DDPStrategy()
        gd.debuginfo(prj="mt", info=f'')
    elif args.strategy == "colossalai_gemini":
        strategy = GeminiStrategy(placement_policy="auto")
        gd.debuginfo(prj="mt", info=f'')
    elif args.strategy == "colossalai_zero2":
        strategy = LowLevelZeroStrategy(stage=2, placement_policy="cuda")
        gd.debuginfo(prj="mt", info=f'')
    elif args.strategy == "colossalai_zero2_cpu":
        strategy = LowLevelZeroStrategy(stage=2, placement_policy="cpu")
        gd.debuginfo(prj="mt", info=f'')
    else:
        raise ValueError(f'Unsupported strategy "{args.strategy}"')

    # configure model
    if args.lora_rank > 0:
        gd.debuginfo(prj="mt", info=f"Lora is not supported yet.")
        args.lora_rank = 0

    with strategy.model_init_context():
        if args.model == "bloom":
            model = BLOOMActor(pretrained=args.pretrain, lora_rank=args.lora_rank, checkpoint=args.grad_checkpoint)
            gd.debuginfo(prj="mt", info=f'')
        elif args.model == "opt":
            model = OPTActor(pretrained=args.pretrain, lora_rank=args.lora_rank, checkpoint=args.grad_checkpoint)
            gd.debuginfo(prj="mt", info=f'')
        elif args.model == "gpt2":
            model = GPTActor(pretrained=args.pretrain, lora_rank=args.lora_rank, checkpoint=args.grad_checkpoint)
            gd.debuginfo(prj="mt", info=f'')
        elif args.model == "llama":
            model = LlamaActor(pretrained=args.pretrain, lora_rank=args.lora_rank, checkpoint=args.grad_checkpoint)
            gd.debuginfo(prj="mt", info=f'')
        elif args.model == "chatglm":
            model = ChatGLMActor(pretrained=args.pretrain)
            gd.debuginfo(prj="mt", info=f'')
        else:
            raise ValueError(f'Unsupported model "{args.model}"')

        model.to(torch.bfloat16).to(torch.cuda.current_device())

    # configure tokenizer
    if args.model == "gpt2":
        tokenizer = GPT2Tokenizer.from_pretrained("gpt2" if args.tokenizer is None else args.tokenizer)
        tokenizer.pad_token = tokenizer.eos_token
        gd.debuginfo(prj="mt", info=f'')
    elif args.model == "bloom":
        tokenizer = BloomTokenizerFast.from_pretrained(
            "/share/hf_model/bloom-560m" if args.tokenizer is None else args.tokenizer
        )
        tokenizer.pad_token = tokenizer.eos_token
        gd.debuginfo(prj="mt", info=f'')
    elif args.model == "opt":
        tokenizer = AutoTokenizer.from_pretrained("/share/hf_model/opt-350m" if args.tokenizer is None else args.tokenizer)
        tokenizer.pad_token = tokenizer.eos_token
        gd.debuginfo(prj="mt", info=f'')
    elif args.model == "llama":
        tokenizer = LlamaTokenizer.from_pretrained(
            "/share/hf_model/llama-tokenizer" if args.tokenizer is None else args.tokenizer
        )
        tokenizer.eos_token = "<\s>"
        tokenizer.pad_token = tokenizer.unk_token
        gd.debuginfo(prj="mt", info=f'')
    elif args.model == "chatglm":
        tokenizer = ChatGLMTokenizer.from_pretrained(
            "THUDM/chatglm-6b" if args.tokenizer is None else args.tokenizer, trust_remote_code=True
        )
        gd.debuginfo(prj="mt", info=f'')
    else:
        raise ValueError(f'Unsupported model "{args.model}"')

    # configure optimizer
    if args.strategy.startswith("colossalai"):
        optim = HybridAdam(model.parameters(), lr=args.lr, clipping_norm=1.0)
        gd.debuginfo(prj="mt", info=f'')
    else:
        optim = Adam(model.parameters(), lr=args.lr)
        gd.debuginfo(prj="mt", info=f'')

    logf = f'init_dataset_sample'
    gd.emb_start(info=logf)

    # configure dataset
    if args.dataset == "/share/hf_model/self_instruct":
        train_data = load_dataset(args.dataset, "super_natural_instructions", split="train")
        eval_data = load_dataset(args.dataset, "super_natural_instructions", split="test")

        if args.max_datasets_size is not None:
            train_data = train_data.select(range(min(args.max_datasets_size, len(train_data))))
            eval_data = eval_data.select(range(min(args.max_datasets_size, len(eval_data))))

        train_dataset = SFTDataset(train_data, tokenizer, args.max_len)
        eval_dataset = SFTDataset(eval_data, tokenizer, args.max_len)

        gd.debuginfo(prj="mt", info=f'')

    else:
        train_dataset = SupervisedDataset(
            tokenizer=tokenizer,
            data_path=args.dataset,
            max_datasets_size=args.max_datasets_size,
            max_length=args.max_len,
        )
        eval_dataset = None

        gd.debuginfo(prj="mt", info=f'')

    if dist.is_initialized() and dist.get_world_size() > 1:
        train_sampler = DistributedSampler(
            train_dataset,
            shuffle=True,
            seed=42,
            drop_last=True,
            rank=dist.get_rank(),
            num_replicas=dist.get_world_size(),
        )
        if eval_dataset is not None:
            eval_sampler = DistributedSampler(
                eval_dataset,
                shuffle=False,
                seed=42,
                drop_last=False,
                rank=dist.get_rank(),
                num_replicas=dist.get_world_size(),
            )
            gd.debuginfo(prj="mt", info=f'')

        gd.debuginfo(prj="mt", info=f'')
    else:
        train_sampler = None
        eval_sampler = None
        gd.debuginfo(prj="mt", info=f'')

    gd.emb_end(info=logf)

    train_dataloader = DataLoader(
        train_dataset,
        shuffle=(train_sampler is None),
        sampler=train_sampler,
        batch_size=args.batch_size,
        pin_memory=True,
    )

    if eval_dataset is not None:
        eval_dataloader = DataLoader(
            eval_dataset,
            shuffle=(eval_sampler is None),
            sampler=eval_sampler,
            batch_size=args.batch_size,
            pin_memory=True,
        )
        gd.debuginfo(prj="mt", info=f'')
    else:
        eval_dataloader = None
        gd.debuginfo(prj="mt", info=f'')

    logf = f'sft_model'
    gd.emb_start(info=logf)

    num_update_steps_per_epoch = len(train_dataloader) // args.accumulation_steps
    max_steps = math.ceil(args.max_epochs * num_update_steps_per_epoch)
    gd.debuginfo(prj="mt", info=f'num_update_steps_per_epoch={num_update_steps_per_epoch}')
    gd.debuginfo(prj="mt", info=f'max_steps={max_steps}')

    lr_scheduler = get_scheduler(
        "cosine", optim, num_warmup_steps=math.ceil(max_steps * 0.03), num_training_steps=max_steps
    )
    gd.debuginfo(prj="mt", info=f'lr_scheduler={lr_scheduler}')

    strategy_dict = strategy.prepare(dict(model=model, optimizer=optim, lr_scheduler=lr_scheduler))
    gd.debuginfo(prj="mt", info=f'strategy_dict={strategy_dict}')

    model = strategy_dict["model"]
    optim = strategy_dict["optimizer"]
    lr_scheduler = strategy_dict["lr_scheduler"]

    gd.debuginfo(prj="mt", info=f'model={model}')
    gd.debuginfo(prj="mt", info=f'optim={optim}')
    gd.debuginfo(prj="mt", info=f'lr_scheduler={lr_scheduler}')

    gd.emb_end(info=logf)

    logf = f'trainer.fit'
    gd.emb_start(info=logf)

    trainer = SFTTrainer(
        model=model,
        strategy=strategy,
        optim=optim,
        lr_scheduler=lr_scheduler,
        max_epochs=args.max_epochs,
        accumulation_steps=args.accumulation_steps,
    )

    gd.debuginfo(prj="mt", info=f'trainer={trainer}')

    # logger = get_dist_logger()
    logger = None
    trainer.fit(
        train_dataloader=train_dataloader,
        eval_dataloader=eval_dataloader,
        logger=logger,
        log_dir=args.log_dir,
        use_wandb=args.use_wandb,
    )
    gd.emb_end(info=logf)

    if args.lora_rank > 0 and args.merge_lora_weights:
        gd.debuginfo(prj="mt", info=f'')
        from coati.models.lora import LORA_MANAGER

        # NOTE: set model to eval to merge LoRA weights
        LORA_MANAGER.merge_weights = True
        model.eval()

    # save model checkpoint after fitting on only rank0
    strategy.save_pretrained(model, path=args.save_path, tokenizer=tokenizer)

    # save optimizer checkpoint on all ranks
    if args.need_optim_ckpt:
        gd.debuginfo(prj="mt", info=f'')
        strategy.save_optimizer(
            trainer.optimizer, "rm_optim_checkpoint_%d.pt" % (torch.cuda.current_device()), only_rank0=False
        )


if __name__ == "__main__":

    gd.debuginfo(prj='mt', info=f'=================') # 不被计入
    gd.setIgnore(prj='mt', ignore=20)

    gd.prjenable('ALL')  #打开项目flag

    logpath = f'/logColossalAI/_log_tmps_chat_SFT_/'

    if not os.path.exists(logpath):
        os.makedirs(logpath)

    gd.emb_mode(path=logpath, embedded_mode=True)

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--strategy",
        choices=["ddp", "colossalai_gemini", "colossalai_zero2", "colossalai_zero2_cpu"],
        default="colossalai_zero2",
    )
    parser.add_argument("--model", choices=["gpt2", "bloom", "opt", "llama", "chatglm"], default="bloom")
    parser.add_argument("--tokenizer", type=str, default=None)
    parser.add_argument("--pretrain", type=str, default=None)
    parser.add_argument("--dataset", type=str, default=None)
    parser.add_argument("--max_datasets_size", type=int, default=None)
    parser.add_argument("--save_path", type=str, default="output")
    parser.add_argument("--need_optim_ckpt", type=bool, default=False)
    parser.add_argument("--max_epochs", type=int, default=3)
    parser.add_argument("--batch_size", type=int, default=4)
    parser.add_argument("--max_len", type=int, default=512)
    parser.add_argument("--lora_rank", type=int, default=0, help="low-rank adaptation matrices rank")
    parser.add_argument("--merge_lora_weights", type=bool, default=True)
    parser.add_argument("--lr", type=float, default=5e-6)
    parser.add_argument("--accumulation_steps", type=int, default=8)
    parser.add_argument("--log_dir", default="logs", type=str)
    parser.add_argument("--use_wandb", default=False, action="store_true")
    parser.add_argument("--grad_checkpoint", default=False, action="store_true")
    args = parser.parse_args()

    gd.debuginfo(prj="mt", info=f'args={args}')
    train(args)

    gd.emb_mode(embedded_mode=False)
