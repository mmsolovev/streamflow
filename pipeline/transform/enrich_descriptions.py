"""
Legacy entrypoint kept for backwards compatibility.

Prefer: `python pipeline/runtime/enrich_descriptions.py`.
"""

from pipeline.runtime.enrich_descriptions import process  # noqa: F401


if __name__ == "__main__":
    import asyncio

    asyncio.run(process())

