import cv2, threading, queue, os, time, json, boto3, tempfile, logging, sys, glob, easyocr, re
import numpy as np
from fastapi import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from threading import Event
from redis import Redis
from concurrent.futures import ThreadPoolExecutor

redis = Redis.from_url(os.environ.get("REDIS_URL"), decode_responses=True)

AWS_ACCESS_KEY = os.environ.get("AWS_ACCESS_KEY")
AWS_SECRET_KEY = os.environ.get("AWS_SECRET_KEY")
AWS_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-west-2")
BUCKET_NAME = os.environ.get("BUCKET_NAME")

# initialize boto3 client for aws
s3 = boto3.client(
    "s3",
    aws_access_key_id=AWS_ACCESS_KEY,
    aws_secret_access_key=AWS_SECRET_KEY,
    region_name=AWS_REGION
)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)
logger.info("Worker started and waiting for jobs...")

def process_video(file_path, resolution, job_id, page):
    reader = easyocr.Reader(['en'])

    def extract_frames(video_path, ):
        cap = cv2.VideoCapture(video_path)
        step = cap.get(cv2.CAP_PROP_FPS)
        frame_idx = 0
        next_capture_second = 0.0

        if not cap.isOpened():
            os.remove(video_path)
            raise HTTPException(status_code=400, detail="Could not open video")

        while cap.isOpened() and not pause_queue.is_set():
            ret, frame = cap.read()
            if not ret:
                break
            current_time = frame_idx / step
            if current_time >= next_capture_second:
                try:
                    frame_queue.put(frame, timeout=1)
                except queue.Full:
                    pass
                next_capture_second += 1.0
            frame_idx += 1
        
        pause_queue.set()

        cap.release()

    def extract_info_from_frame(frame, roi):
        full_frame = frame
        if roi:
            x, y, w, h = roi
            frame = frame[y:y+h, x:x+w]

        easyResult = reader.readtext(frame, mag_ratio=2.0)
        easyNum = [item[1] for item in easyResult]

        if page == 'ba':
            if easyNum:
                cleanNum = re.sub(r'[a-zA-Z\s\D]', '', easyNum[0])
                if cleanNum:
                    cleanNum = int(cleanNum)
                else:
                    cleanNum = 0
            else:
                cleanNum = 0

            nonlocal prevNum
            easyNum = [str(cleanNum - prevNum)]
            prevNum = cleanNum

        # scan for special node using template matching
        fullGray = cv2.cvtColor(full_frame, cv2.COLOR_BGR2GRAY)
        fatal = cv2.imread("resources/special_node.png")
        mapae = cv2.imread("resources/mapae_icon.png")
        cont = cv2.imread("resources/cont_active.png")
        ror = cv2.imread("resources/ror_active.png")

        grayFatal = cv2.cvtColor(fatal, cv2.COLOR_BGR2GRAY)
        grayMapae = cv2.cvtColor(mapae, cv2.COLOR_BGR2GRAY)
        grayCont = cv2.cvtColor(cont, cv2.COLOR_BGR2GRAY)
        grayRor = cv2.cvtColor(ror, cv2.COLOR_BGR2GRAY)

        resFatal = cv2.matchTemplate(fullGray, grayFatal, cv2.TM_CCOEFF_NORMED)
        resMapae = cv2.matchTemplate(fullGray, grayMapae, cv2.TM_CCOEFF_NORMED)
        resCont = cv2.matchTemplate(fullGray, grayCont, cv2.TM_CCOEFF_NORMED)
        resRor = cv2.matchTemplate(fullGray, grayRor, cv2.TM_CCOEFF_NORMED)

        min_val, max_val_fatal, min_loc, max_loc = cv2.minMaxLoc(resFatal)
        min_val, max_val_mapae, min_loc, max_loc = cv2.minMaxLoc(resMapae)
        min_val_cont, max_val_cont, min_loc_cont, max_loc_cont = cv2.minMaxLoc(resCont)
        min_val_ror, max_val_ror, min_loc_ror, max_loc_ror = cv2.minMaxLoc(resRor)

        threshold = 0.75
        cont_threshold = 0.6
        
        if max_val_fatal >= threshold or max_val_mapae >= threshold:
            fatal_active = True
        else:
            fatal_active = False

        cont_loc = np.where(resCont >= cont_threshold)
        if len(cont_loc[0]) > 1:
            if cont_loc[0][0] == cont_loc[0][1]:
                cont_active = True
            else:
                cont_active = False
        else:
            cont_active = False

        ror_loc = np.where(resRor >= threshold)
        if len(ror_loc[0]) > 1:
            if ror_loc[0][0] == ror_loc[0][1]:
                ror_active = True
            else:
                ror_active = False
        else:
            ror_active = False

        return [easyNum, fatal_active, cont_active, ror_active]

    # get all frames from video and add all numbers from each frame to list
    def process_frames(roi):
        while not pause_queue.is_set() or not frame_queue.empty():
            try:
                frame = frame_queue.get(timeout=1)
                result = extract_info_from_frame(frame, roi)

                if result[0]:
                    logging.info(f"OCR Result: {result}")
                    values.append(result)

                # update redis with values for live results
                redis.set(f"result:{job_id}", json.dumps(values))
            except queue.Empty:
                continue
    
    def process(video_path, roi):

        reader_thread = threading.Thread(target=extract_frames, args=(video_path, ))
        analyzer_thread = threading.Thread(target=process_frames, args=((roi),))

        reader_thread.start()
        analyzer_thread.start()

        reader_thread.join()
        analyzer_thread.join()

    # get ROI from resolution selected

    if page == 'culvert':
        ROI_dict = {
            "2560x1440" : (1375, 190, 240, 65),
            "1920x1080" : (995, 85, 150, 50),
            "1366x768" : (725, 90, 125, 40),
            "1280x720" : (725, 100, 140, 35),
            "1024x768" : (725, 95, 130, 32)
        }
    elif page == 'ba':
        ROI_dict = {
            "2560x1440" : (172, 1015, 240, 65),
            "1920x1080" : (172, 1015, 240, 65),
            "1366x768" : (172, 1015, 240, 65),
            "1280x720" : (172, 1015, 240, 65),
            "1024x768" : (172, 1015, 240, 65)
        }
    else:
        ROI_dict = {
            "2560x1440" : (1375, 190, 240, 65),
            "1920x1080" : (995, 85, 150, 50),
            "1366x768" : (725, 90, 125, 40),
            "1280x720" : (725, 100, 140, 35),
            "1024x768" : (725, 95, 130, 32)
        }

    roi = ROI_dict[resolution]

    prevNum = 0
    values = []
    frame_queue = queue.Queue()
    lock = threading.Lock()
    pause_queue = Event()

    process(file_path, roi)

    # free temp files
    for file in glob.glob("/tmp/*.png"):
        try:
            os.remove(file)
        except:
            pass
    
    return values

if __name__ == "__main__":
    while True:
        try:
            job_data = redis.brpop("video_jobs")
            if job_data:
                _, job_json = job_data
                job = json.loads(job_json)
                job_id = job["job_id"]
                job_reso = job["resolution"]
                job_page = job["page"]
                logger.info(f"Job Found: {job_id}")
                redis.set(f"status:{job_id}", "processing")

                with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as temp:
                    logger.info(f"Downloading from bucket={BUCKET_NAME}, key={job_id}")
                    s3.download_file(BUCKET_NAME, f"videos/{job_id}.mp4", temp.name)
                    temp_path = temp.name
                    temp.close()

                try:
                    result = process_video(temp_path, job_reso, job_id, job_page)

                    # save result
                    logger.info(f"JOB COMPLETED")
                    redis.set(f"result:{job_id}", json.dumps(result))
                    redis.set(f"status:{job_id}", "complete")
                    pass
                finally:
                    os.unlink(temp_path)

            else:
                time.sleep(1)
        except Exception as e:
            logger.info("Worker loop crashed: %s", e)
