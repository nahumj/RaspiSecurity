# python pi_surveillance.py --conf conf.json

# import the necessary packages
# from dropbox.client import DropboxOAuth2FlowNoRedirect
# from dropbox.client import DropboxClient
from picamera.array import PiRGBArray
from picamera import PiCamera
from utils import send_email, TempImage
import argparse
import warnings
import datetime
import json
import time
import cv2
import pathlib

SYNC_PATH = pathlib.Path("/home/pi/rpi-sync/security/")

conf = {
	"min_upload_seconds": 0.5,
	"min_motion_frames": 8,
	"camera_warmup_time": 10,
	"delta_thresh": 5,
	"blur_size": [21, 21], 
	"resolution": [640, 480],
	"fps": 16,
	"min_area": 5000,
}

# initialize the camera and grab a reference to the raw camera capture
camera = PiCamera()
camera.resolution = tuple(conf["resolution"])
camera.framerate = conf["fps"]
rawCapture = PiRGBArray(camera, size=tuple(conf["resolution"]))

# allow the camera to warmup, then initialize the average frame, last
# uploaded timestamp, and frame motion counter
print("[INFO] warming up...")
time.sleep(conf["camera_warmup_time"])
avg = None
lastUploaded = datetime.datetime.now()
motionCounter = 0
print('[INFO] talking raspi started !!')

# capture frames from the camera
for f in camera.capture_continuous(rawCapture, format="bgr", use_video_port=True):
	# grab the raw NumPy array representing the image and initialize
	# the timestamp and occupied/unoccupied text
	frame = f.array
	timestamp = datetime.datetime.now()
	found_motion = False

	######################################################################
	# COMPUTER VISION
	######################################################################
	# resize the frame, convert it to grayscale, and blur it
	# TODO: resize image here into cmaller sizes 
	gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
	gray = cv2.GaussianBlur(gray, tuple(conf['blur_size']), 0)

	# if the average frame is None, initialize it
	if avg is None:
		print("[INFO] recording background")
		avg = gray.copy().astype("float")
		avg_recorded_time = datetime.datetime.now()
		rawCapture.truncate(0)
		continue

	# accumulate the weighted average between the current frame and
	# previous frames, then compute the difference between the current
	# frame and running average
	frameDelta = cv2.absdiff(gray, cv2.convertScaleAbs(avg))
	cv2.accumulateWeighted(gray, avg, 0.5)

	# threshold the delta image, dilate the thresholded image to fill
	# in holes, then find contours on thresholded image
	thresh = cv2.threshold(frameDelta, conf["delta_thresh"], 255,
		cv2.THRESH_BINARY)[1]
	thresh = cv2.dilate(thresh, None, iterations=2)
	im2 ,cnts, _ = cv2.findContours(thresh.copy(), cv2.RETR_EXTERNAL,
		cv2.CHAIN_APPROX_SIMPLE)

	# loop over the contours
	for c in cnts:
		# if the contour is too small, ignore it
		if cv2.contourArea(c) < conf["min_area"]:
			continue

		# compute the bounding box for the contour, draw it on the frame,
		# and update the text
		(x, y, w, h) = cv2.boundingRect(c)
		cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
		found_motion = True

	# draw the text and timestamp on the frame
	ts = timestamp.strftime("%A %d %B %Y %I:%M:%S%p")
	# cv2.putText(frame, "Room Status: {}".format(text), (10, 20),
	# 	cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
	cv2.putText(frame, ts, (10, frame.shape[0] - 10), cv2.FONT_HERSHEY_SIMPLEX,
		0.35, (0, 0, 255), 1)


	###################################################################################
	# LOGIC
	###################################################################################

	# check to see if the room is occupied
	if found_motion:
		# save occupied frame
		date_str = timestamp.strftime("%Y-%m-%d")
		date_dir = SYNC_PATH / date_str
		date_dir.mkdir(parents=True, exist_ok=True)
		image_path = date_dir / "{}_{}.jpg".format(timestamp, motionCounter)

		cv2.imwrite(str(image_path), frame)
		print("[INFO] Found movement!! Wrote to", image_path)

	# clear the stream in preparation for the next frame
	rawCapture.truncate(0)
