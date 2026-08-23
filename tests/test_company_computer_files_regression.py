import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentie.core import company_computer_files as files


class CompanyComputerFileTransferRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name)
        self.workspace.joinpath("report.docx").write_bytes(b"docx-data")
        self.patch = patch.object(files, "WORKSPACE", self.workspace)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def test_upload_writes_real_bytes_to_guest_agent(self):
        calls=[]
        def qga(payload, timeout=10):
            calls.append(payload)
            action=payload["execute"]
            if action=="guest-file-open":return {"return":7}
            if action=="guest-file-write":
                data=base64.b64decode(payload["arguments"]["buf-b64"])
                return {"return":{"count":len(data)}}
            if action=="guest-file-close":return {"return":{}}
            raise AssertionError(action)
        with patch.object(files.computer,"start",return_value={}), patch.object(files,"_ensure_guest_dir"), patch.object(files.computer,"_qga_request",side_effect=qga), patch.object(files.computer,"guest_exec",return_value={"exitcode":0}), patch.object(files.computer,"touch_activity"):
            result=files.upload_workspace_file("report.docx")
        self.assertEqual(result["guest_path"],"/home/agentie/Agentie Inbox/report.docx")
        writes=[x for x in calls if x["execute"]=="guest-file-write"]
        self.assertEqual(base64.b64decode(writes[0]["arguments"]["buf-b64"]),b"docx-data")

    def test_download_copies_guest_bytes_into_workspace(self):
        payloads=[b"pdf-",b"data"]
        def qga(payload, timeout=10):
            action=payload["execute"]
            if action=="guest-file-open":return {"return":9}
            if action=="guest-file-close":return {"return":{}}
            if action=="guest-file-read":
                if payloads:
                    value=payloads.pop(0);return {"return":{"buf-b64":base64.b64encode(value).decode(),"eof":False}}
                return {"return":{"buf-b64":"","eof":True}}
            raise AssertionError(action)
        with patch.object(files.computer,"start",return_value={}), patch.object(files.computer,"_qga_request",side_effect=qga), patch.object(files.computer,"touch_activity"):
            result=files.download_guest_file("/home/agentie/Downloads/file.pdf","file.pdf")
        self.assertEqual(self.workspace.joinpath("file.pdf").read_bytes(),b"pdf-data")
        self.assertEqual(result["size_bytes"],8)

    def test_transfer_rejects_host_path_outside_workspace(self):
        with self.assertRaises(ValueError):
            files._safe_host_file(str(Path(self.temp.name).parent / "secret.txt"))

    def test_transfer_rejects_guest_path_outside_agentie_home(self):
        with self.assertRaises(ValueError):
            files._safe_guest_path("/etc/passwd",default_dir=files.GUEST_INBOX)

    def test_transfer_rejects_guest_traversal(self):
        with self.assertRaises(ValueError):
            files._safe_guest_path("../escape.txt",default_dir=files.GUEST_INBOX)


if __name__=="__main__":unittest.main()
