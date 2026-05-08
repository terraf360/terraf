"""
Permite invocar el CLI de TerraF directamente con Python:

    python -m terraf --help
    python -m terraf analyze
    python -m terraf gui
"""
from terraf.cli import app

app()
