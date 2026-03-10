from app import create_app
from app.config import AppConfig


app = create_app()

if __name__ == "__main__":
    config = AppConfig()
    app.run(host="0.0.0.0", port=config.PORT, debug=config.DEBUG)
