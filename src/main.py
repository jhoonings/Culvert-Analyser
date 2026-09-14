import tempfile, uuid, json, boto3, os, logging
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path
from itertools import groupby
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from threading import Event
from redis import Redis

# --------- CONFIG ---------
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://jhoonings.github.io"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
redis = Redis.from_url(os.environ.get('REDIS_URL'), decode_responses=True)
AWS_ACCESS_KEY = os.environ.get('AWS_ACCESS_KEY')
AWS_SECRET_KEY = os.environ.get('AWS_SECRET_KEY')
AWS_REGION = os.environ.get('AWS_DEFAULT_REGION')
BUCKET_NAME = os.environ.get('BUCKET_NAME')

s3 = boto3.client(
    "s3",
    aws_access_key_id=AWS_ACCESS_KEY,
    aws_secret_access_key=AWS_SECRET_KEY,
    region_name=AWS_REGION
)

boto3.set_stream_logger(name="botocore", level=logging.DEBUG)

logger = logging.getLogger("uvicorn.error")

logger.info(f"AWS_ACCESS_KEY={os.environ.get('AWS_ACCESS_KEY')}")
logger.info(f"AWS_SECRET_KEY exists={os.environ.get('AWS_SECRET_KEY') is not None}")
logger.info(f"AWS_DEFAULT_REGION={os.environ.get('AWS_DEFAULT_REGION')}")
logger.info(f"BUCKET_NAME={os.environ.get('BUCKET_NAME')}")
# ---------------------------

@app.get("/")
def home():
    return {"status": "ok", "message": "Good Response"}

@app.post("/analyse")
async def anaylse(file: UploadFile, resolution: str = File(...), page: str = File(...)):
    # reset global vars
    
    job_id = str(uuid.uuid4())

    # strip suspicious path components
    basename = os.path.basename(file.filename)
    safename = Path(basename).name

    # validate uploaded file as mp4
    ext = os.path.splitext(safename)[1].lower()
    if ext not in {".mp4", ".mov", ".avi"}:
        raise HTTPException(status_code=400, detail="Invalid file type.")
    
    # enforce size limits on file
    max_size = 1000 * 1024 * 1024  # 1 GB
    file_size = 0

    while chunk := file.file.read(1024 * 1024):
        file_size += len(chunk)
        if file_size > max_size:
            raise HTTPException(status_code=400, detail="File too large.")
        
    file.file.seek(0)
        
    try:
        try:
            logger.info(f"Uploading {safename} to s3://{BUCKET_NAME}/{job_id}")
            s3.upload_fileobj(file.file, BUCKET_NAME, f"videos/{job_id}.mp4")
            logger.info("Upload successful")
        except Exception as e:
            logger.error("S3 upload failed", exc_info=True)  # full traceback
            raise HTTPException(status_code=500, detail=f"S3 upload failed: {str(e)}")
        
        job_data = {"job_id" : job_id, "resolution": resolution, "page": page}
        redis.lpush("video_jobs", json.dumps(job_data))

        return {"job_id": job_id, "status": "processing"}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
    
@app.get("/status/{job_id}")
def get_status(job_id: str):
    result = redis.get(f"result:{job_id}")
    status = redis.get(f"status:{job_id}")
    if result:
        if status == "complete":
            return {"task_id": job_id, "results": json.loads(result), "status": "complete"}
        return {"task_id": job_id, "results": json.loads(result), "status": "processing"}
    return {"task_id": job_id, "results": "", "status": "processing"}
