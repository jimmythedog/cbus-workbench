"""Evaluate the visibility subset found in MMC MDFs, independently of Qt.

True/False are known results; None means a referenced NV/EV is unread (absent
or None). Invalid syntax raises MdfVisibilityError (a ValueError), never an unknown result. This is
not a general JSON Logic implementation. Slot conditions are not supported.
"""

import logging

logger = logging.getLogger(__name__)
# Match logging_config.TRACE without importing its Qt-dependent paths module.
_TRACE = 5
_COMPARISONS = {"==", "!=", ">", "<=", "in"}
_ACCESSORS = {"NV", "EV", "NVbit", "EVbit"}


class MdfVisibilityError(ValueError):
    """A malformed or unsupported MDF visibility condition or input byte."""


def evaluate_visibility(
    condition: object,
    nv_values: dict[int, int | None],
    ev_values: dict[int, int | None],
) -> bool | None:
    """Evaluate a visibility condition using one-based byte dictionaries.

    All branches are checked, even when another branch determines the result,
    so unsupported syntax cannot be concealed by short-circuit evaluation.
    No values or expressions are modified.
    """
    logger.log(_TRACE, "Evaluate MDF visibility condition=%r", condition)
    try:
        result = _condition(condition, nv_values, ev_values)
    except MdfVisibilityError:
        logger.exception(
            "Invalid or unsupported MDF visibility condition=%r", condition
        )
        raise
    logger.log(_TRACE, "MDF visibility result=%r condition=%r", result, condition)
    return result


def _condition(condition, nv_values, ev_values):
    if not isinstance(condition, dict):
        raise MdfVisibilityError("Visibility condition must be an object")
    if set(condition) == {"JLL"}:
        return _expression(condition["JLL"], nv_values, ev_values)
    for selector, accessor in (
        ("nv", "NV"),
        ("ev", "EV"),
        ("nvBit", "NVbit"),
        ("evBit", "EVbit"),
    ):
        if set(condition) != {selector, "equals"}:
            continue
        index = condition[selector]
        maximum = 255
        if selector in ("nvBit", "evBit"):
            if not isinstance(index, dict) or set(index) != {"index", "bit"}:
                raise MdfVisibilityError("Bit selector needs index and bit")
            index = [index["index"], index["bit"]]
            maximum = 1
        expected = condition["equals"]
        if type(expected) is not int or not 0 <= expected <= maximum:
            raise MdfVisibilityError(f"equals must be an integer from 0 to {maximum}")
        value = _operand({accessor: index}, nv_values, ev_values)
        return None if value is None else value == expected
    raise MdfVisibilityError("Unsupported visibility condition")


def _operand(operand, nv_values, ev_values):
    """Read a literal or byte/bit accessor; missing bytes remain unknown."""
    if type(operand) in (int, bool):
        return operand
    if not isinstance(operand, dict) or len(operand) != 1:
        raise MdfVisibilityError(
            "Operand must be an integer, boolean or NV/EV accessor"
        )
    accessor, index = next(iter(operand.items()))
    if accessor not in _ACCESSORS:
        raise MdfVisibilityError(f"Unsupported value accessor: {accessor}")
    bit = None
    if accessor in ("NVbit", "EVbit"):
        if not isinstance(index, list) or len(index) != 2:
            raise MdfVisibilityError("Bit accessor needs [index, bit]")
        index, bit = index
        if type(bit) is not int or not 0 <= bit <= 7:
            raise MdfVisibilityError("Bit must be an integer from 0 to 7")
    if type(index) is not int or not 1 <= index <= 255:
        raise MdfVisibilityError("NV/EV index must be an integer from 1 to 255")
    values = nv_values if accessor in ("NV", "NVbit") else ev_values
    value = values.get(index)
    if value is None:
        logger.log(
            _TRACE, "MDF visibility value unread accessor=%s index=%s", accessor, index
        )
        return None
    if type(value) is not int or not 0 <= value <= 255:
        raise MdfVisibilityError(
            f"{accessor} index {index} must contain a byte or None"
        )
    result = value if bit is None else (value >> bit) & 1
    logger.log(
        _TRACE,
        "MDF visibility value accessor=%s index=%s bit=%s byte=%s result=%s",
        accessor,
        index,
        bit,
        value,
        result,
    )
    return result


def _expression(expression, nv_values, ev_values):
    """Evaluate only the observed JLL predicates and boolean combinations."""
    if not isinstance(expression, dict) or len(expression) != 1:
        raise MdfVisibilityError("JLL expression needs exactly one operator")
    operator, arguments = next(iter(expression.items()))
    if operator in ("and", "or"):
        if not isinstance(arguments, list) or not arguments:
            raise MdfVisibilityError("and/or need a nonempty list of expressions")
        results = [_expression(child, nv_values, ev_values) for child in arguments]
        # Use identity checks: None must never behave like False.
        decisive = operator == "or"
        if any(result is decisive for result in results):
            result = decisive
        elif any(result is None for result in results):
            result = None
        else:
            result = not decisive
        logger.log(
            _TRACE,
            "MDF visibility operator=%s children=%r result=%r",
            operator,
            results,
            result,
        )
        return result
    if operator not in _COMPARISONS:
        raise MdfVisibilityError(f"Unsupported JLL operator: {operator}")
    if not isinstance(arguments, list) or len(arguments) != 2:
        raise MdfVisibilityError(f"{operator} needs two operands")
    left = _operand(arguments[0], nv_values, ev_values)
    if operator == "in":
        right = arguments[1]
        if not isinstance(right, list) or any(
            type(item) not in (int, bool) for item in right
        ):
            raise MdfVisibilityError("in needs a list of integer or boolean literals")
    else:
        right = _operand(arguments[1], nv_values, ev_values)
    if left is None or right is None:
        return None
    # Bit access returns 0/1, which compare directly with JLL false/true literals.
    if operator == "==":
        return left == right
    if operator == "!=":
        return left != right
    if operator == ">":
        return left > right
    if operator == "<=":
        return left <= right
    return left in right
