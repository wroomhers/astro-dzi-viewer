# -*- coding: utf-8 -*-
import time
import zmq
import cv2

ZMQ_BIND = "tcp://127.0.0.1:5555"   # sunucu SUB.connect ile buna bağlanıyor
TOPIC = b"img"

def main():
    ctx = zmq.Context.instance()
    pub = ctx.socket(zmq.PUB)
    pub.setsockopt(zmq.CONFLATE, 1)
    pub.bind(ZMQ_BIND)

    # PUB/SUB warm-up
    time.sleep(0.3)

    cap = cv2.VideoCapture(0, cv2.CAP_V4L2)  # Linux'ta genelde doğru backend
    if not cap.isOpened():
        raise RuntimeError("Kamera açılamadı (VideoCapture(0) başarısız)")

    # İsteğe bağlı çözünürlük
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    print("PUB ready on", ZMQ_BIND)
    i = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.05)
                continue
            ok, enc = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            if not ok:
                time.sleep(0.01)
                continue
            pub.send_multipart([TOPIC, enc.tobytes()])
            # print(f"[PUB] frame {i}, bytes={len(enc)}")  # debug istersen aç
            i += 1
            time.sleep(0.03)  # ~30 FPS hedefi; gerekirse azalt
    finally:
        cap.release()
        pub.close(0)
        ctx.term()

if __name__ == "__main__":
    main()