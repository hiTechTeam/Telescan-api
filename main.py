"""Application entry point."""

# -- Imports

import uvicorn

# --

APP = "src.api.v1.server:app"
HOST = "0.0.0.0"
PORT = 8000

# --

if __name__ == "__main__":

    uvicorn.run(
        app=APP,
        host=HOST,
        port=PORT,
        reload=True,
    )
