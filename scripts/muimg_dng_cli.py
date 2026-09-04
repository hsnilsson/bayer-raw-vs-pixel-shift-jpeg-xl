from __future__ import annotations

"""Run muimg while suppressing tifffile's non-DNG shaped-series description.

muimg 0.1.20260718.1648 already suppresses this metadata on SubIFDs, but not on
IFD0. When IFD0 is a reduced preview, tifffile otherwise writes its dimensions
as ImageDescription and later warns that the DNG series shape is inconsistent.
"""

from muimg import dngio


_prepare_ifd_args = dngio._prepare_ifd_args


def prepare_ifd_args_without_shaped_metadata(*args, **kwargs):
    result = _prepare_ifd_args(*args, **kwargs)
    result["metadata"] = None
    return result


dngio._prepare_ifd_args = prepare_ifd_args_without_shaped_metadata

from muimg.cli import cli  # noqa: E402


if __name__ == "__main__":
    cli()
