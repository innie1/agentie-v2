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

    def test_upload_routes_real_file_through_backend_facade(self):
        with patch.object(files.computer,"start",return_value={}), patch.object(files,"_ensure_guest_dir"), patch.object(files.computer,"guest_upload",return_value=9) as upload, patch.object(files.computer,"guest_exec",return_value={"exitcode":0}), patch.object(files.computer,"touch_activity"):
            result=files.upload_workspace_file("report.docx")
        upload.assert_called_once_with(self.workspace / "report.docx", "/home/agentie/Agentie Inbox/report.docx", chunk_bytes=files.CHUNK_BYTES)
        self.assertEqual(result["guest_path"],"/home/agentie/Agentie Inbox/report.docx")

    def test_download_copies_guest_bytes_into_workspace(self):
        def download(source, destination, **kwargs):
            destination.write_bytes(b"pdf-data")
            return 8
        with patch.object(files.computer,"start",return_value={}), patch.object(files.computer,"guest_download",side_effect=download) as transfer, patch.object(files.computer,"touch_activity"):
            result=files.download_guest_file("/home/agentie/Downloads/file.pdf","file.pdf")
        self.assertEqual(transfer.call_args.args[0], "/home/agentie/Downloads/file.pdf")
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

    def test_file_layer_has_no_qemu_transport_dependency(self):
        source = Path("agentie/core/company_computer_files.py").read_text(encoding="utf-8")
        self.assertIn("company_computer_backend", source)
        self.assertNotIn("_qga_request", source)
        self.assertNotIn("company_computer_guest_agent", source)


if __name__=="__main__":unittest.main()
