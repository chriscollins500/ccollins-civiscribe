"""Civitai/A1111 display aliases for current common ComfyUI sampler values."""

from __future__ import annotations

from .sanitize import metadata_scalar

_SAMPLERS = {
    "ddim": "DDIM",
    "ddpm": "DDPM",
    "deis": "DEIS",
    "dpm_2": "DPM2",
    "dpm_2_ancestral": "DPM2 a",
    "dpm_adaptive": "DPM adaptive",
    "dpm_fast": "DPM fast",
    "dpmpp_2m": "DPM++ 2M",
    "dpmpp_2m_cfg_pp": "DPM++ 2M CFG++",
    "dpmpp_2m_sde": "DPM++ 2M SDE",
    "dpmpp_2m_sde_gpu": "DPM++ 2M SDE GPU",
    "dpmpp_2s_ancestral": "DPM++ 2S a",
    "dpmpp_2s_ancestral_cfg_pp": "DPM++ 2S a CFG++",
    "dpmpp_3m_sde": "DPM++ 3M SDE",
    "dpmpp_3m_sde_gpu": "DPM++ 3M SDE GPU",
    "dpmpp_sde": "DPM++ SDE",
    "dpmpp_sde_gpu": "DPM++ SDE GPU",
    "euler": "Euler",
    "euler_ancestral": "Euler a",
    "euler_ancestral_cfg_pp": "Euler a CFG++",
    "euler_cfg_pp": "Euler CFG++",
    "heun": "Heun",
    "heunpp2": "Heun++",
    "ipndm": "IPNDM",
    "ipndm_v": "IPNDM V",
    "lcm": "LCM",
    "lms": "LMS",
    "sa_solver": "SA Solver",
    "sa_solver_pece": "SA Solver PECE",
    "uni_pc": "UniPC",
    "uni_pc_bh2": "UniPC BH2",
}
_SCHEDULERS = {
    "align_your_steps": "Align Your Steps",
    "alignyoursteps": "Align Your Steps",
    "ays sd1": "AYS SD1",
    "ays sdxl": "AYS SDXL",
    "ays svd": "AYS SVD",
    "beta57": "Beta57",
    "ddim_uniform": "DDIM Uniform",
    "exponential": "Exponential",
    "flux2": "Flux2",
    "karras": "Karras",
    "kl_optimal": "KL Optimal",
    "linear_quadratic": "Linear Quadratic",
    "polyexponential": "Polyexponential",
    "sgm_uniform": "SGM Uniform",
    "sigmoid_offset": "Sigmoid Offset",
}


def display_sampler(value: str | None) -> str | None:
    """Map known current ComfyUI values while preserving safe custom names."""

    safe = metadata_scalar(value)
    return None if safe is None else _SAMPLERS.get(safe.casefold(), safe)


def display_scheduler(value: str | None) -> str | None:
    """Map known scheduler values while preserving safe custom names."""

    safe = metadata_scalar(value)
    return None if safe is None else _SCHEDULERS.get(safe.casefold(), safe)


__all__ = ["display_sampler", "display_scheduler"]
