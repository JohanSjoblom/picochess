# upload_handler.py

import os
import base64
import pam
import tornado.web
from tornado import escape

from utilities import Observable
from dgt.api import Event


UPLOAD_BASE_DIR = "/opt/picochess/games"
UPLOAD_DIR = "uploads"
os.makedirs(os.path.join(UPLOAD_BASE_DIR, UPLOAD_DIR), exist_ok=True)


class UploadHandler(tornado.web.RequestHandler):
    def prepare(self):
        auth_header = self.request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Basic "):
            self.request_auth()
            return

        try:
            auth_decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
            username, password = auth_decoded.split(":", 1)
        except Exception:
            self.request_auth()
            return

        if not pam.pam().authenticate(username, password):
            self.request_auth()
            return

        self.current_user = username

    def request_auth(self):
        self.set_status(401)
        self.set_header("WWW-Authenticate", 'Basic realm="Upload Area"')
        self.finish("Authentication required")

    async def post(self):
        if not hasattr(self, "current_user"):
            return  # Auth failed

        if "file" not in self.request.files:
            self.set_status(400)
            self.finish("No file uploaded")
            return

        fileinfo = self.request.files["file"][0]
        original_name = fileinfo["filename"]

        # Check if uploaded file is a PGN file (by name)
        if not original_name.lower().endswith(".pgn"):
            self.set_status(400)
            self.finish("Only .pgn files are allowed.")
            return

        upload_file = os.path.join(UPLOAD_BASE_DIR, UPLOAD_DIR, original_name)
        file_rel_path = os.path.join(UPLOAD_DIR, original_name)

        try:
            with open(upload_file, "wb") as f:
                f.write(fileinfo["body"])
                event = Event.READ_GAME(pgn_filename=file_rel_path)
                await Observable.fire(event)
        except Exception as e:
            self.set_status(500)
            self.finish(f"Failed to save file: {str(e)}")
            return

        user = escape.xhtml_escape(self.current_user)
        name = escape.xhtml_escape(original_name)

        self.write(
            f"<div style='font-family:sans-serif; padding:2em; font-size:1.2em;'>"
            f"<h2>User '{user}' uploaded '{name}' to games/uploads/.</h2>"
            "<br><br>"
            "<form action='/' method='get'>"
            "<button type='submit' style='"
            "width:100%; padding:1em; margin:1em 0; font-size:1.2em; "
            "background:#007bff; color:white; border:none; border-radius:0.4em; "
            "cursor:pointer;'>Go to game</button>"
            "</form>"
            "<form action='/upload' method='get'>"
            "<button type='submit' style='"
            "width:100%; padding:1em; margin:1em 0; font-size:1.2em; "
            "background:#007bff; color:white; border:none; border-radius:0.4em; "
            "cursor:pointer;'>Back to Uploads</button>"
            "</form>"
            "</div>"
        )
