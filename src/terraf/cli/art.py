"""
Diseño visual de la CLI — banner, paleta de colores y helpers de output.
"""

import sys

# Reconfigurar stdout/stderr a UTF-8 antes de crear cualquier Console.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

from rich.console import Console  # noqa: E402
from rich.table import Table      # noqa: E402
from rich.text import Text        # noqa: E402
from rich.theme import Theme      # noqa: E402

from terraf import __version__    # noqa: E402

# ──────────────────────────────────────────────────────────────────────────────
# Paleta y consola compartida
# ──────────────────────────────────────────────────────────────────────────────

THEME = Theme({
    "primary":      "bold green",
    "accent":       "cyan",
    "muted":        "dim white",
    "ok":           "bold green",
    "warn":         "bold yellow",
    "err":          "bold red",
    "step.done":    "green",
    "step.pending": "bright_black",
})

console = Console(theme=THEME)

# ──────────────────────────────────────────────────────────────────────────────
# Planeta Tierra — ASCII art detallado
#
#   Bright green = continentes (letras M, H densas)
#   Cyan         = atmósfera, océano, contorno
# ──────────────────────────────────────────────────────────────────────────────

# La línea 11 contiene `""""` (4 comillas) que cierra prematuramente r"""..."""
# → se divide la cadena justo en ese punto y se concatena.
_EARTH_RAW = (
    r"""            _-o#&&*''''?d:>b\_
          _o/"`''  '',, dMF9MMMMMHo_
       .o&#'        `"MbHMMMMMMMMMMMHo.
     .o"" '         vodM*$&&HMMMMMMMMMM?.
    ,'              $M&ood,~'`(&##MMMMMMH\
   /               ,MMMMMMM#b?#bobMMMMHMMML
  &              ?MMMMMMMMMMMMMMMMM7MMM$R*Hk
 ?$.            :MMMMMMMMMMMMMMMMMMM/HMMM|`*L
|               |MMMMMMMMMMMMMMMMMMMMbMH'   T,
$H#:            `*MMMMMMMMMMMMMMMMMMMMb#}'  `?
]MMH#             ""*"""          # ← cierra aquí para evitar """"
    + '""""'                      # ← las 4 comillas problemáticas
    + r"""*#MMMMMMMMMMMMM'    -
MMMMMb_                   |MMMMMMMMMMMP'     :
HMMMMMMMHo                 `MMMMMMMMMT       .
?MMMMMMMMP                  9MMMMMMMM}       -
-?MMMMMMM                  |MMMMMMMMM?,d-    '
 :|MMMMMM-                 `MMMMMMMT .M|.   :
  .9MMM[                    &MMMMM*' `'    .
   :9MMk                    `MMM#"        -
     &M}                     `          .-
      `&.                             .
        `~,   .                     ./
            . _                  .-
              '`--._,dd###pp=""'"""
)

_LAND = set("MH")   # caracteres de masa terrestre → verde brillante


def _build_earth() -> Text:
    """Colorea el ASCII art carácter a carácter."""
    t = Text(no_wrap=True)
    for ch in _EARTH_RAW:
        if ch == "\n":
            t.append("\n")
        elif ch == " ":
            t.append(" ")
        elif ch in _LAND:
            t.append(ch, style="bright_green")
        else:
            t.append(ch, style="cyan")
    return t


# ──────────────────────────────────────────────────────────────────────────────
# TERRAF — ANSI Shadow
# ──────────────────────────────────────────────────────────────────────────────

LOGOTYPE = (
    "[green]████████╗███████╗██████╗ ██████╗  █████╗ ███████╗[/green]\n"
    "[green]╚══██╔══╝██╔════╝██╔══██╗██╔══██╗██╔══██╗██╔════╝[/green]\n"
    "[green]   ██║   █████╗  ██████╔╝██████╔╝███████║█████╗  [/green]\n"
    "[green]   ██║   ██╔══╝  ██╔══██╗██╔══██╗██╔══██║██╔══╝  [/green]\n"
    "[green]   ██║   ███████╗██║  ██║██║  ██║██║  ██║██║     [/green]\n"
    "[green]   ╚═╝   ╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝     [/green]"
)

SUBTITLE = f"[dim]  Exploración minera desde la terminal  ·  v{__version__}[/dim]"

BANNER = LOGOTYPE + "\n\n" + SUBTITLE

# ──────────────────────────────────────────────────────────────────────────────
# Símbolos
# ──────────────────────────────────────────────────────────────────────────────

SYM = {
    "ok":      "[step.done]✓[/step.done]",
    "pending": "[step.pending]○[/step.pending]",
    "warn":    "[warn]![/warn]",
    "err":     "[err]x[/err]",
    "arrow":   "[accent]->[/accent]",
}

# ──────────────────────────────────────────────────────────────────────────────
# Pantalla de bienvenida
# ──────────────────────────────────────────────────────────────────────────────

def print_welcome() -> None:
    """
    Pantalla de bienvenida: planeta a la izquierda, TERRAF a la derecha.

        [estrellas]

        [Tierra]    [████████╗...]
        [Tierra]    [╚══██╔══╝...]
           ...          ...
        [Tierra]    [subtítulo]
    """
    console.print()
    console.print("[dim]   *    .     *       .     *    .   *    .   *[/dim]")
    console.print("[dim] .    *    .     *    .    *       .      *    [/dim]")
    console.print()

    # Grid lado a lado: planeta izquierda, TERRAF+subtítulo derecha
    grid = Table.grid(padding=(0, 3))
    grid.add_column(vertical="middle")  # planeta
    grid.add_column(vertical="middle")  # logotipo

    logo = Text.from_markup(LOGOTYPE + "\n\n" + SUBTITLE)

    grid.add_row(_build_earth(), logo)
    console.print(grid)
    console.print()


def print_banner() -> None:
    """Banner compacto (sin planeta) para --version."""
    console.print()
    console.print(BANNER)
    console.print()


# ──────────────────────────────────────────────────────────────────────────────
# Helpers de output
# ──────────────────────────────────────────────────────────────────────────────

def success(msg: str) -> None:
    console.print(f"  {SYM['ok']}  {msg}")


def warning(msg: str) -> None:
    console.print(f"  {SYM['warn']}  {msg}")


def error(msg: str) -> None:
    console.print(f"  {SYM['err']}  {msg}")


def next_step(cmd: str, extra: str = "") -> None:
    console.print()
    suffix = f"  [muted]{extra}[/muted]" if extra else ""
    console.print(f"  [muted]Siguiente paso:[/muted]  [accent]{cmd}[/accent]{suffix}")
    console.print()


def divider() -> None:
    console.print("[dim]" + "-" * 60 + "[/dim]")
