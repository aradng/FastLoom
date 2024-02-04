# transcript
## Install
1. Clone the repo
1. Local (Only for debugging and development):
    1. Run `python3.11 -m venv .venv`
    1. Install poetry and run `poetry env use python3.11`
    1. Run `poetry install`
    1. Run `./init_vosk.py`
    1. Run `./build.sh`
    1. Run `docker-compose up -d`
    1. Run `docker-compose up -d web --scale web=0`
    1. Run `uvicorn app:app --host 0.0.0.0 --port 8000 --reload`
1. Docker (Recommended):
    1. Run `./build.sh`
    1. Run `docker-compose up -d`
    1. Run `docker-compose exec -it worker sh`
    1. Run `./init_vosk.py`

## TODO
- [ ] Add old vid/vtt/log deletion
- [x] streams data deletion on startup
- [x] fix revoke
