import ast
import io
from contextlib import redirect_stdout

from agents import function_tool


SAFE_BUILTINS = {
    "abs": abs,
    "all": all,
    "any": any,
    "bool": bool,
    "dict": dict,
    "enumerate": enumerate,
    "float": float,
    "int": int,
    "len": len,
    "list": list,
    "max": max,
    "min": min,
    "print": print,
    "range": range,
    "round": round,
    "set": set,
    "sorted": sorted,
    "str": str,
    "sum": sum,
    "tuple": tuple,
    "zip": zip,
}

ALLOWED_NODES = {
    ast.Module,
    ast.Expr,
    ast.Assign,
    ast.AugAssign,
    ast.Name,
    ast.Load,
    ast.Store,
    ast.Constant,
    ast.List,
    ast.Tuple,
    ast.Set,
    ast.Dict,
    ast.BinOp,
    ast.UnaryOp,
    ast.BoolOp,
    ast.Compare,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.USub,
    ast.UAdd,
    ast.And,
    ast.Or,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.In,
    ast.NotIn,
    ast.Call,
    ast.keyword,
    ast.If,
    ast.For,
    ast.While,
    ast.Break,
    ast.Continue,
    ast.Pass,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
    ast.comprehension,
    ast.IfExp,
    ast.Subscript,
    ast.Slice,
}


def _validate_python(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        if type(node) not in ALLOWED_NODES:
            raise ValueError(f"Unsupported Python operation: {type(node).__name__}")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in SAFE_BUILTINS:
                raise ValueError("Only approved built-in functions may be called.")
        if isinstance(node, ast.Name) and node.id.startswith("__"):
            raise ValueError("Dunder names are not allowed.")


@function_tool
def run_python(code: str) -> str:
    """Run restricted Python for calculations and in-memory data processing.

    Imports, file access, network access, attribute access, subprocesses, and
    system commands are intentionally disabled. Use Agentie's file tools for
    workspace file operations instead.
    """
    if len(code) > 8000:
        raise ValueError("Python code is too long for the restricted runner.")

    tree = ast.parse(code, mode="exec")
    _validate_python(tree)

    stdout = io.StringIO()
    globals_dict = {"__builtins__": SAFE_BUILTINS}
    locals_dict = {}

    with redirect_stdout(stdout):
        exec(compile(tree, "<agentie-python>", "exec"), globals_dict, locals_dict)

    output = stdout.getvalue().strip()
    if output:
        return output[:12000]

    visible = {
        key: value
        for key, value in locals_dict.items()
        if not key.startswith("_") and isinstance(value, (str, int, float, bool, list, tuple, dict, set))
    }
    return repr(visible)[:12000] if visible else "Python completed successfully with no output."
