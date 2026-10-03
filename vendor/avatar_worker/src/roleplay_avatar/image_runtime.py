"""Memory/latency controls shared by local Diffusers image pipelines."""


def configure_pipeline(pipe, options):
    offload = options.get("offload", "model")
    if offload not in {"model", "sequential", "none"}:
        raise ValueError("Image offload must be model, sequential or none")
    compile_model = options.get("compile", False)
    if compile_model and offload != "none":
        raise ValueError("Image compilation requires offload=none")
    tiling = options.get("vae_tiling", hasattr(pipe.vae, "enable_tiling"))
    slicing = options.get("vae_slicing", hasattr(pipe.vae, "enable_slicing"))
    if tiling and not hasattr(pipe.vae, "enable_tiling"):
        raise ValueError("This image VAE does not support tiling")
    if slicing and not hasattr(pipe.vae, "enable_slicing"):
        raise ValueError("This image VAE does not support slicing")
    if tiling:
        pipe.vae.enable_tiling()
    if slicing:
        pipe.vae.enable_slicing()
    if offload == "model":
        pipe.enable_model_cpu_offload()
    elif offload == "sequential":
        pipe.enable_sequential_cpu_offload()
    else:
        pipe.to("cuda")
    if compile_model:
        import torch

        pipe.transformer = torch.compile(pipe.transformer, mode="reduce-overhead")
    return {"offload": offload, "compile": compile_model,
            "vae_tiling": tiling, "vae_slicing": slicing}
