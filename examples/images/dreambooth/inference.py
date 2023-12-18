import torch
from diffusers import DiffusionPipeline
from pydebug import gd, infoTensor
model_id = "<Your Model Path>"
gd.debuginfo(prj="mt", info=f"Loading model... from{model_id}")

pipe = DiffusionPipeline.from_pretrained(model_id, torch_dtype=torch.float16).to("cuda")

prompt = "A photo of an apple."
image = pipe(prompt, num_inference_steps=50, guidance_scale=7.5).images[0]

image.save("output.png")
