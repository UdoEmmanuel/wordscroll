"""
Entry point for the packaged backend .exe (see PACKAGING.md) — equivalent to
`uvicorn main:app --host 127.0.0.1 --port 8765`, but as a real script
PyInstaller can freeze, importing the FastAPI app object directly rather
than uvicorn's string-based "main:app" dynamic import. That string form
works fine unfrozen, but PyInstaller's static analysis can't see through it
to know main.py needs bundling — importing it directly here gives
PyInstaller an ordinary `import main` to discover instead.
"""
import main
import uvicorn

if __name__ == "__main__":
    uvicorn.run(main.app, host="127.0.0.1", port=8765)
