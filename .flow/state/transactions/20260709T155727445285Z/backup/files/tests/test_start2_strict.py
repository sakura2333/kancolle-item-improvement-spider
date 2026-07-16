import os
import unittest
from unittest.mock import patch

from util.start2 import start2_utils


class Start2StrictModeTest(unittest.TestCase):
    def test_strict_mode_rejects_remote_index_failure(self):
        with patch.dict(os.environ, {"DATA_PACKAGE_STRICT": "1"}, clear=False), patch.object(
            start2_utils, "fetch_remote_index", side_effect=RuntimeError("offline")
        ):
            with self.assertRaisesRegex(RuntimeError, "strict mode could not validate remote index"):
                start2_utils.update_start2_if_needed()

    def test_strict_mode_rejects_current_data_download_failure(self):
        with patch.dict(os.environ, {"DATA_PACKAGE_STRICT": "1"}, clear=False), patch.object(
            start2_utils, "fetch_remote_index", return_value=["new-version"]
        ), patch.object(start2_utils, "get_local_version", return_value="old-version"), patch.object(
            start2_utils, "fetch_start2", side_effect=RuntimeError("offline")
        ):
            with self.assertRaisesRegex(RuntimeError, "strict mode could not download current data"):
                start2_utils.update_start2_if_needed()

    def test_non_strict_mode_keeps_last_local_data_on_index_failure(self):
        with patch.dict(os.environ, {"DATA_PACKAGE_STRICT": "0"}, clear=False), patch.object(
            start2_utils, "fetch_remote_index", side_effect=RuntimeError("offline")
        ), patch.object(start2_utils, "load_start2_readers") as load_readers:
            start2_utils.update_start2_if_needed()
            load_readers.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
