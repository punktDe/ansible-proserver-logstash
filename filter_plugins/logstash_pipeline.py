from ansible.errors import AnsibleFilterError
from ansible.module_utils.common._collections_compat import Mapping, Sequence


def _format_value(value: object) -> str:
    """Format a Python value as a Logstash config value (right-hand side of =>)."""
    if value is None:
        return '""'
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        # Escape backslashes and double quotes; wrap in double quotes
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(value, Sequence) and not isinstance(value, str):
        parts = [_format_value(item) for item in value]
        return "[ " + ", ".join(parts) + " ]"
    if isinstance(value, Mapping):
        pairs = []
        for k, v in value.items():
            key_str = str(k)
            if not (key_str.startswith('"') and key_str.endswith('"')):
                key_str = key_str.replace("\\", "\\\\").replace('"', '\\"')
                key_str = f'"{key_str}"'
            pairs.append(f"{key_str} => {_format_value(v)}")
        return "{ " + " ".join(pairs) + " }"
    # Fallback: stringify and quote
    return f'"{str(value).replace(chr(92), chr(92)*2).replace(chr(34), chr(92)+chr(34))}"'


def _format_plugin_block(plugin_name: str, settings: Mapping) -> str:
    """Format a single plugin block: plugin_name { key => value ... }."""
    lines = [f"  {plugin_name} {{"]
    for k, v in settings.items():
        if v is None:
            continue
        lines.append(f"    {k} => {_format_value(v)}")
    lines.append("  }")
    return "\n".join(lines)


def _section_to_blocks(section: object) -> list[tuple[str, Mapping]]:
    """
    Normalize a section (input/filter/output) into a list of (plugin_name, settings) pairs.
    Supports:
      - dict: { plugin_name: settings_dict } or { plugin_name: [settings1, settings2] }
      - list: [ { plugin_name: settings }, ... ]
    """
    blocks: list[tuple[str, Mapping]] = []
    if isinstance(section, Mapping):
        for plugin_name, config in section.items():
            if isinstance(config, list):
                for item in config:
                    if isinstance(item, Mapping):
                        blocks.append((plugin_name, item))
                    else:
                        raise AnsibleFilterError(
                            f"logstash_pipeline: plugin '{plugin_name}' list must contain dicts, got {type(item).__name__}"
                        )
            elif isinstance(config, Mapping):
                blocks.append((plugin_name, config))
            else:
                raise AnsibleFilterError(
                    f"logstash_pipeline: plugin '{plugin_name}' value must be a dict or list of dicts, got {type(config).__name__}"
                )
    elif isinstance(section, list):
        for item in section:
            if isinstance(item, Mapping) and len(item) == 1:
                plugin_name = next(iter(item))
                blocks.append((plugin_name, item[plugin_name]))
            else:
                raise AnsibleFilterError(
                    "logstash_pipeline: section list must contain single-key dicts (plugin name => settings), got invalid item"
                )
    else:
        raise AnsibleFilterError(
            f"logstash_pipeline: section must be a dict or list, got {type(section).__name__}"
        )
    return blocks


def _render_section(section_name: str, section: object) -> str:
    """Render one top-level section (input, filter, output) as Logstash config."""
    blocks = _section_to_blocks(section)
    if not blocks:
        return ""
    parts = [f"{section_name} {{"]
    for plugin_name, settings in blocks:
        parts.append(_format_plugin_block(plugin_name, settings))
    parts.append("}")
    return "\n".join(parts)


def logstash_pipeline(pipeline_dict: object) -> str:
    """
    Convert an Ansible dictionary to a Logstash pipeline configuration string.

    The dictionary must have optional top-level keys: input, filter, output.
    Each key's value describes one or more plugins for that section.

    Plugin sections can be:
    - A dict mapping plugin names to a settings dict (or list of settings dicts for multiple blocks):
      input:
        beats:
          port: 5044
          host: "0.0.0.0"
        http:
          - port: 3333
            tags: gateway
          - port: 4444
            tags: billing
    - A list of single-key dicts (plugin name -> settings):
      input:
        - beats:
            port: 5044
        - file:
            path: "/var/log/messages"

    Values in settings support strings, numbers, booleans, lists, and nested dicts (hashes).
    """
    if not isinstance(pipeline_dict, Mapping):
        raise AnsibleFilterError(
            f"logstash_pipeline: argument must be a dict, got {type(pipeline_dict).__name__}"
        )
    sections = []
    for section_name in ("input", "filter", "output"):
        if section_name not in pipeline_dict:
            continue
        section = pipeline_dict[section_name]
        if section is None:
            continue
        rendered = _render_section(section_name, section)
        if rendered:
            sections.append(rendered)
    if not sections:
        raise AnsibleFilterError(
            "logstash_pipeline: dict must contain at least one of: input, filter, output"
        )
    return "\n\n".join(sections)


class FilterModule:
    """Ansible filter plugin entry point."""

    def filters(self) -> dict[str, callable]:
        return {"logstash_pipeline": logstash_pipeline}
