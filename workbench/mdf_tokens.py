"""MDF replacement text (format issue 0.15, sections 12 and 13)."""

import re

# Keep arbitrary token names case-sensitive. Only legacy 'channel' is explicitly
# case-insensitive. Real CANARGB MDFs use both ${palette1} and ${palette 1}.
TOKEN = re.compile(r"\$\{([^{}]+?)\}")


def normalise_token(identifier: str) -> tuple[str, str]:
    """Return the MDF name and decimal number used by lookup and YAML storage."""
    match = re.fullmatch(r"(.+?\D)\s*(\d+)", identifier.strip())
    if match is None:
        raise ValueError(f"Invalid MDF token identifier: {identifier!r}")
    name = match[1].rstrip()
    if name.lower() == "channel":
        name = "channel"
    return name, str(int(match[2]))


def token_defaults(data: dict) -> dict[tuple[str, str], str]:
    """Discover referenced tokens, with new defaults before legacy channel names."""
    identifiers = set()

    def scan(value):
        if isinstance(value, str):
            for match in TOKEN.finditer(value):
                try:
                    identifiers.add(normalise_token(match[1]))
                except ValueError:
                    pass  # Structural placeholders are not numbered user names.
        elif isinstance(value, dict):
            for child in value.values():
                scan(child)
        elif isinstance(value, list):
            for child in value:
                scan(child)

    scan(data)
    defaults = {}
    for name, definition in data.get("tokens", {}).items():
        for number, value in definition.get("defaultNames", {}).items():
            defaults[normalise_token(f"{name}{number}")] = value
    for number, value in data.get("channelNames", {}).items():
        defaults.setdefault(normalise_token(f"channel{number}"), value)
    # Legacy MDFs can declare channels without referencing every one in text.
    channel_count = max(
        [data.get("numberOfChannels", 0)]
        + [int(number) for name, number in defaults if name == "channel"]
    )
    identifiers.update(("channel", str(n)) for n in range(1, channel_count + 1))
    identifiers.update(defaults)
    return {
        key: defaults.get(key, "".join(key))
        for key in sorted(identifiers, key=lambda key: (key[0], int(key[1])))
    }


def normalise_overrides(values: dict) -> dict:
    """Store only nonempty user values; defaults continue to belong to the MDF."""
    if not isinstance(values, dict):
        raise TypeError("Expected MDF token overrides")
    result = {}
    for name, numbers in values.items():
        if not isinstance(name, str) or not isinstance(numbers, dict):
            raise TypeError("Expected MDF token names mapped to numbered values")
        for number, value in numbers.items():
            if not isinstance(value, str):
                raise TypeError("Expected text for an MDF token override")
            token_name, token_number = normalise_token(f"{name}{number}")
            if value.strip():
                result.setdefault(token_name, {})[token_number] = value.strip()
    return result


def substitute_tokens(data: dict, overrides: dict) -> dict:
    """Resolve text in a presentation copy, leaving descriptor definitions intact.

    Substitution is one pass: a user name containing ${...} is literal text.
    """
    defaults = token_defaults(data)
    values = normalise_overrides(overrides)

    def replace(match):
        try:
            name, number = normalise_token(match[1])
        except ValueError:
            return match[0]  # Leave structural resolution to the MDF renderer.
        return values.get(name, {}).get(
            number, defaults.get((name, number), name + number)
        )

    def visit(value):
        if isinstance(value, str):
            return TOKEN.sub(replace, value)
        if isinstance(value, list):
            return [visit(child) for child in value]
        if isinstance(value, dict):
            return {key: visit(child) for key, child in value.items()}
        return value

    return visit(data)
