"""Saved-content semantics shared by workspaces, histories and creator catalogs."""
import json

MODULE_KEYS = {"summary": "result", "mindmap": "mindmap_markdown", "notes": "notes", "qa": "qa_pairs"}


def decode_payload(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return {}
    return value if isinstance(value, dict) else {}


def present_modules(value):
    payload = decode_payload(value)
    present = []
    for module, key in MODULE_KEYS.items():
        content = payload.get(key)
        if module == "summary":
            valid = isinstance(content, dict) and isinstance(content.get("summary"), str) and bool(content["summary"].strip())
        elif module == "qa":
            valid = isinstance(content, list) and any(isinstance(p, dict) and all(isinstance(p.get(k), str) and p[k].strip() for k in ("question", "answer")) for p in content)
        else:
            valid = isinstance(content, str) and bool(content.strip())
        if valid:
            present.append(module)
    return present


def content_state(value=None, has_subtitle=False, subtitle_text=None):
    payload = decode_payload(value)
    modules = present_modules(payload)
    count = len(modules)
    description = payload.get("description_summary")
    stale = []
    metadata = payload.get("_artifacts") or {}
    if isinstance(metadata, dict):
        import hashlib
        import config
        for module in modules:
            meta = metadata.get(module)
            if not isinstance(meta, dict) or not meta:
                continue
            version = getattr(config, {"summary": "SUMMARY", "mindmap": "MINDMAP", "notes": "NOTES", "qa": "QANDA"}[module] + "_PROMPT_VERSION")
            revision = hashlib.sha256(subtitle_text.strip().encode()).hexdigest() if subtitle_text is not None else None
            if meta.get("prompt_version") != version or (revision is not None and meta.get("subtitle_revision") != revision):
                stale.append(module)
    return {
        "stale_modules": stale,
        "has_subtitle": bool(has_subtitle), "modules": modules, "module_count": count,
        "coverage": "complete" if count == 4 else "partial" if count else "subtitle" if has_subtitle else "empty",
        "has_description_summary": bool(isinstance(description, dict) and description.get("summary")),
    }


def register_content_functions(conn):
    from core.cache import _extract_video_key
    conn.create_function("vm_video_key", 1, _extract_video_key, deterministic=True)
    conn.create_function("vm_module_count", 1, lambda value: len(present_modules(value)), deterministic=True)
