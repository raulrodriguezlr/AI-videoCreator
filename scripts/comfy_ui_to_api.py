"""Convert a ComfyUI UI-format workflow (with subgraphs) to API format.

API format = {node_id: {"class_type": ..., "inputs": {...}}}. Widget values
are mapped by the input order served by the live server's /object_info, and
v2 subgraph nodes are inlined (their internal graph spliced in, boundary
links rewired). Validates every class_type against the server.

Usage:
  python comfy_ui_to_api.py <ui_workflow.json> <out_api.json> [server]
"""
from __future__ import annotations

import json
import sys
import urllib.request

SERVER = "http://127.0.0.1:8188"

_SKIP_TYPES = {"MarkdownNote", "Note"}
# widgets that exist in the UI but are not API inputs
_CONTROL_WIDGET = "control_after_generate"


def fetch_object_info(server: str) -> dict:
    with urllib.request.urlopen(f"{server}/object_info", timeout=30) as r:
        return json.load(r)


def widget_input_names(class_type: str, info: dict) -> list[str]:
    """Names of inputs that take widget values (not links), in order."""
    spec = info[class_type]["input"]
    names: list[str] = []
    for section in ("required", "optional"):
        for name, decl in spec.get(section, {}).items():
            type_decl = decl[0] if isinstance(decl, list) and decl else decl
            # connection-only types are uppercase identifiers like MODEL/CLIP;
            # widget types are primitives or enum lists
            if isinstance(type_decl, list):
                names.append(name)  # enum dropdown
            elif type_decl in ("INT", "FLOAT", "STRING", "BOOLEAN"):
                names.append(name)
    return names


def all_input_names(class_type: str, info: dict) -> list[str]:
    spec = info[class_type]["input"]
    out = []
    for section in ("required", "optional"):
        out.extend(spec.get(section, {}).keys())
    return out


def _norm_link(l, fresh_id: int) -> list:
    """Normalize a link (list in parent graphs, dict in subgraphs) to
    [id, origin, origin_slot, target, target_slot, type]."""
    if isinstance(l, dict):
        return [fresh_id, l["origin_id"], l["origin_slot"],
                l["target_id"], l["target_slot"], l.get("type")]
    return list(l)


def inline_subgraphs(wf: dict) -> dict:
    """Splice v2 subgraph nodes into the parent graph (one level at a time)."""
    defs = {s["id"]: s for s in (wf.get("definitions", {}) or {}).get("subgraphs", [])}
    if not defs:
        return wf

    while True:
        sub_nodes = [n for n in wf["nodes"] if n["type"] in defs]
        if not sub_nodes:
            return wf
        node = sub_nodes[0]
        sub = defs[node["type"]]
        prefix = f"{node['id']}:"
        io_ids = {str(sub.get("inputNode", {}).get("id")),
                  str(sub.get("outputNode", {}).get("id"))}

        inner_nodes = []
        for n in json.loads(json.dumps(sub["nodes"])):
            n["id"] = f"{prefix}{n['id']}"
            inner_nodes.append(n)

        max_link = max((l[0] for l in wf["links"]), default=0)
        link_map: dict[int, list] = {}
        inner_links = []
        for raw in sub.get("links", []) or []:
            max_link += 1
            l = _norm_link(raw, max_link)
            orig_id = raw["id"] if isinstance(raw, dict) else raw[0]
            for idx in (1, 3):  # remap node refs unless they hit an io node
                if str(l[idx]) not in io_ids:
                    l[idx] = f"{prefix}{l[idx]}"
            link_map[orig_id] = l
            inner_links.append(l)

        parent_in = [l for l in wf["links"] if str(l[3]) == str(node["id"])]
        parent_out = [l for l in wf["links"] if str(l[1]) == str(node["id"])]

        # parent inputs → the internal links born at the input io node
        for slot_idx, sin in enumerate(sub.get("inputs", []) or []):
            ext = next((l for l in parent_in if l[4] == slot_idx), None)
            if ext is None:
                continue
            for lid in sin.get("linkIds", []) or []:
                if lid in link_map:
                    link_map[lid][1], link_map[lid][2] = ext[1], ext[2]
        # internal sources feeding the output io node → parent outputs
        for slot_idx, sout in enumerate(sub.get("outputs", []) or []):
            src = next((link_map[lid] for lid in (sout.get("linkIds") or [])
                        if lid in link_map), None)
            if src is None:
                continue
            for ext in parent_out:
                if ext[2] == slot_idx:
                    ext[1], ext[2] = src[1], src[2]

        # drop links that still touch io pseudo-nodes (fully rewired above)
        inner_links = [l for l in inner_links
                       if str(l[1]) not in io_ids and str(l[3]) not in io_ids]

        wf["nodes"] = [n for n in wf["nodes"] if n["id"] != node["id"]] + inner_nodes
        wf["links"] = [l for l in wf["links"]
                       if str(l[3]) != str(node["id"])] + inner_links


#: utility nodes folded to literal values (also covers packs not installed
#: on the server, e.g. ComfyMath's CM_FloatToInt in the official workflows)
_FOLD = {
    "PrimitiveInt": lambda node, _in: int(node["widgets_values"][0]),
    "PrimitiveFloat": lambda node, _in: float(node["widgets_values"][0]),
    "PrimitiveString": lambda node, _in: node["widgets_values"][0],
    "PrimitiveStringMultiline": lambda node, _in: node["widgets_values"][0],
    "CM_FloatToInt": lambda node, _in: int(float(_in[0])),
    "EmptyImage": None,  # sentinel: keep (real node) — listed for clarity
}


def fold_constants(by_id: dict, incoming: dict) -> dict[str, object]:
    """Resolve foldable nodes to literals (iterate until stable)."""
    values: dict[str, object] = {}
    changed = True
    while changed:
        changed = False
        for nid, node in by_id.items():
            ctype = node["type"]
            fn = _FOLD.get(ctype)
            if fn is None or nid in values:
                continue
            ins = []
            ok = True
            for slot_idx, _sin in enumerate(node.get("inputs", []) or []):
                link = incoming.get((nid, slot_idx))
                if link is None:
                    continue
                if link[0] in values:
                    ins.append(values[link[0]])
                else:
                    ok = False
                    break
            if ok:
                values[nid] = fn(node, ins)
                changed = True
    return values


def to_api(wf: dict, info: dict) -> dict:
    wf = inline_subgraphs(wf)
    by_id = {str(n["id"]): n for n in wf["nodes"]}
    incoming: dict[tuple[str, int], list] = {}
    for l in wf["links"]:
        incoming[(str(l[3]), l[4])] = [str(l[1]), l[2]]
    folded = fold_constants(by_id, incoming)

    api: dict[str, dict] = {}
    for nid, node in by_id.items():
        ctype = node["type"]
        if ctype in _SKIP_TYPES or nid in folded:
            continue
        if ctype not in info:
            raise SystemExit(f"unknown class_type on server: {ctype}")
        inputs: dict = {}
        # linked inputs (UI node lists its input slots in order)
        for slot_idx, sin in enumerate(node.get("inputs", []) or []):
            link = incoming.get((nid, slot_idx))
            if not link:
                continue
            if link[0] in folded:
                inputs[sin["name"]] = folded[link[0]]
            elif link[0] in by_id and by_id[link[0]]["type"] not in _SKIP_TYPES:
                inputs[sin["name"]] = link
        # widget inputs — iterate ALL widget slots in declared order; a
        # widget converted to a link still holds its stale value in
        # widgets_values, so consume-and-discard those instead of shifting
        # every later widget one position (the batch_size=960 class of bug).
        wvals = list(node.get("widgets_values", []) or [])
        wi = 0
        for name in widget_input_names(ctype, info):
            if wi >= len(wvals):
                break
            val = wvals[wi]
            wi += 1
            if name in ("seed", "noise_seed") and wi < len(wvals) \
                    and isinstance(wvals[wi], str):
                wi += 1  # hidden control_after_generate value
            if name not in inputs:
                inputs[name] = val
        api[nid] = {"class_type": ctype, "inputs": inputs}
    return api


def main() -> None:
    src, dst = sys.argv[1], sys.argv[2]
    server = sys.argv[3] if len(sys.argv) > 3 else SERVER
    info = fetch_object_info(server)
    wf = json.loads(open(src, encoding="utf-8").read())
    api = to_api(wf, info)
    open(dst, "w", encoding="utf-8").write(json.dumps(api, indent=2))
    print(f"OK {len(api)} nodes -> {dst}")


if __name__ == "__main__":
    main()
