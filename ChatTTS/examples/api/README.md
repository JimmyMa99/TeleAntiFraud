# Generating voice with ChatTTS via API

## Install requirements

Install `FastAPI` and `requests`:

```
pip install -r examples/api/requirements.txt
```

## Run API server

```
fastapi dev examples/api/main_new_new.py --host 0.0.0.0 --port 8006
```

## Generate audio using requests

```
python examples/api/client.py
```

mp3 audio files will be saved to the `output` directory.
