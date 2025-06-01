import unittest
from unittest.mock import patch, MagicMock
import os
import cv2 # Import for cv2.error
import ffmpeg # Import for ffmpeg.Error
import inspect # For checking class attributes

# Assuming semantic_analyzer.py is in the parent directory or accessible via PYTHONPATH
from semantic_analyzer import (
    get_file_type,
    extract_text_from_document, SUPPORTED_DOCUMENT_MIME_TYPES,
    extract_image_features, SUPPORTED_IMAGE_MIME_TYPES,
    extract_media_metadata, SUPPORTED_MEDIA_MIME_TYPES,
    generate_tags, STOP_WORDS
)

# Mock 'magic.MagicException' as it's raised by the magic library
class MockMagicException(Exception): # Custom exception for mocking
    pass

class TestGetFileType(unittest.TestCase):
    @patch('semantic_analyzer.os.path.exists')
    @patch('semantic_analyzer.os.path.isfile')
    @patch('semantic_analyzer.magic.from_file')
    def test_get_file_type_success(self, mock_magic_from_file, mock_isfile, mock_exists):
        mock_exists.return_value = True
        mock_isfile.return_value = True
        mock_magic_from_file.return_value = "image/jpeg"
        self.assertEqual(get_file_type("dummy.jpg"), "image/jpeg")

    @patch('semantic_analyzer.os.path.exists')
    def test_get_file_type_not_exists(self, mock_exists):
        mock_exists.return_value = False
        self.assertEqual(get_file_type("nonexistent.txt"), "Error: File not found")

    @patch('semantic_analyzer.os.path.exists')
    @patch('semantic_analyzer.os.path.isfile')
    def test_get_file_type_not_a_file(self, mock_isfile, mock_exists):
        mock_exists.return_value = True
        mock_isfile.return_value = False
        self.assertEqual(get_file_type("dummy_dir"), "Error: Not a file")

    @patch('semantic_analyzer.os.path.exists')
    @patch('semantic_analyzer.os.path.isfile')
    @patch('semantic_analyzer.magic') # Patch the whole module
    def test_get_file_type_magic_exception(self, mock_magic_module, mock_isfile, mock_exists):
        mock_exists.return_value = True
        mock_isfile.return_value = True
        # Configure the mock module's MagicException and from_file behavior
        mock_magic_module.MagicException = MockMagicException
        mock_magic_module.from_file.side_effect = MockMagicException("Magic error")
        self.assertEqual(get_file_type("dummy.dat"), "Error: python-magic failed - Magic error")

    @patch('semantic_analyzer.os.path.exists')
    @patch('semantic_analyzer.os.path.isfile')
    @patch('semantic_analyzer.magic.from_file')
    def test_get_file_type_unexpected_exception(self, mock_magic_from_file, mock_isfile, mock_exists):
        mock_exists.return_value = True
        mock_isfile.return_value = True
        mock_magic_from_file.side_effect = Exception("Unexpected general error")
        self.assertEqual(get_file_type("dummy.dat"), "Error: An unexpected error occurred - Unexpected general error")


class TestExtractTextFromDocument(unittest.TestCase):
    def setUp(self):
        self.dummy_file_path = "dummy.pdf"

    @patch('semantic_analyzer.os.path.exists', return_value=True)
    @patch('semantic_analyzer.tika_parser.from_file')
    def test_extract_text_success(self, mock_tika_from_file, mock_exists):
        mock_tika_from_file.return_value = {'content': "  Extracted text.  ", 'metadata': {}}
        mime_type = 'application/pdf'
        self.assertEqual(extract_text_from_document(self.dummy_file_path, mime_type), "Extracted text.")

    @patch('semantic_analyzer.os.path.exists', return_value=True)
    def test_extract_text_unsupported_mime(self, mock_exists):
        mime_type = 'image/jpeg'
        self.assertIsNone(extract_text_from_document(self.dummy_file_path, mime_type))

    @patch('semantic_analyzer.os.path.exists', return_value=False)
    def test_extract_text_file_not_found(self, mock_exists):
        self.assertIsNone(extract_text_from_document("nonexistent.pdf", 'application/pdf'))

    @patch('semantic_analyzer.os.path.exists', return_value=True)
    @patch('semantic_analyzer.tika_parser.from_file')
    def test_extract_text_tika_returns_none(self, mock_tika_from_file, mock_exists):
        mock_tika_from_file.return_value = None
        self.assertIsNone(extract_text_from_document(self.dummy_file_path, 'application/pdf'))

    @patch('semantic_analyzer.os.path.exists', return_value=True)
    @patch('semantic_analyzer.tika_parser.from_file')
    def test_extract_text_tika_returns_empty_content(self, mock_tika_from_file, mock_exists):
        mock_tika_from_file.return_value = {'content': "   "}
        self.assertIsNone(extract_text_from_document(self.dummy_file_path, 'application/pdf'))

    @patch('semantic_analyzer.os.path.exists', return_value=True)
    @patch('semantic_analyzer.tika_parser.from_file')
    @patch('builtins.print') # To capture print statements
    def test_extract_text_tika_exception_server_down(self, mock_print, mock_tika_from_file, mock_exists):
        mock_tika_from_file.side_effect = Exception("Tika server is not running")
        result = extract_text_from_document(self.dummy_file_path, 'application/pdf')
        self.assertIsNone(result)
        self.assertTrue(any("CRITICAL: Tika server" in call.args[0] for call in mock_print.call_args_list))

    @patch('semantic_analyzer.os.path.exists', return_value=True)
    @patch('semantic_analyzer.tika_parser.from_file')
    @patch('builtins.print')
    def test_extract_text_tika_general_exception(self, mock_print, mock_tika_from_file, mock_exists):
        mock_tika_from_file.side_effect = Exception("Some other Tika error")
        result = extract_text_from_document(self.dummy_file_path, 'application/pdf')
        self.assertIsNone(result)
        # Ensure critical server down message is NOT printed for general errors
        self.assertFalse(any("CRITICAL: Tika server" in call.args[0] for call in mock_print.call_args_list))


class TestExtractImageFeatures(unittest.TestCase):
    def setUp(self):
        self.dummy_file_path = "dummy.jpg"

    @patch('semantic_analyzer.os.path.exists', return_value=True)
    @patch('semantic_analyzer.cv2.imread')
    @patch('semantic_analyzer.cv2.mean')
    def test_extract_image_features_success_color(self, mock_cv2_mean, mock_cv2_imread, mock_exists):
        mock_img = MagicMock()
        mock_img.shape = (1080, 1920, 3)
        mock_cv2_mean.return_value = (100.0, 150.0, 200.0, 0.0)
        mock_cv2_imread.return_value = mock_img
        expected_features = {
            'dimensions': {'height': 1080, 'width': 1920, 'channels': 3},
            'average_color_bgr': [100.0, 150.0, 200.0]
        }
        self.assertEqual(extract_image_features(self.dummy_file_path, 'image/jpeg'), expected_features)

    @patch('semantic_analyzer.os.path.exists', return_value=True)
    @patch('semantic_analyzer.cv2.imread')
    @patch('semantic_analyzer.cv2.mean')
    def test_extract_image_features_success_grayscale(self, mock_cv2_mean, mock_cv2_imread, mock_exists):
        mock_img = MagicMock()
        mock_img.shape = (600, 800)
        mock_cv2_mean.return_value = (120.0, 120.0, 120.0, 0.0)
        mock_cv2_imread.return_value = mock_img
        expected_features = {
            'dimensions': {'height': 600, 'width': 800, 'channels': 1},
            'average_color_bgr': [120.0, 120.0, 120.0]
        }
        self.assertEqual(extract_image_features(self.dummy_file_path, 'image/png'), expected_features)

    @patch('semantic_analyzer.os.path.exists', return_value=True)
    def test_extract_image_unsupported_mime(self, mock_exists):
        self.assertIsNone(extract_image_features(self.dummy_file_path, 'application/pdf'))

    @patch('semantic_analyzer.os.path.exists', return_value=True)
    @patch('semantic_analyzer.cv2.imread')
    def test_extract_image_loading_fails(self, mock_cv2_imread, mock_exists):
        mock_cv2_imread.return_value = None
        self.assertIsNone(extract_image_features(self.dummy_file_path, 'image/jpeg'))

    @patch('semantic_analyzer.os.path.exists', return_value=True)
    @patch('semantic_analyzer.cv2.imread')
    def test_extract_image_cv2_exception(self, mock_cv2_imread, mock_exists):
        # cv2.error needs to be an actual exception type for `isinstance` checks if any,
        # or just be a generic Exception if semantic_analyzer catches `cv2.error` specifically.
        # The code catches cv2.error, so it's better to use it.
        mock_cv2_imread.side_effect = cv2.error("OpenCV error")
        self.assertIsNone(extract_image_features(self.dummy_file_path, 'image/jpeg'))


class TestExtractMediaMetadata(unittest.TestCase):
    def setUp(self):
        self.dummy_file_path = "dummy.mp4"

    @patch('semantic_analyzer.os.path.exists', return_value=True)
    @patch('semantic_analyzer.ffmpeg.probe')
    def test_extract_media_metadata_success(self, mock_ffmpeg_probe, mock_exists):
        mock_ffmpeg_probe.return_value = {
            'streams': [
                {'codec_type': 'video', 'codec_name': 'h264', 'width': 1920, 'height': 1080, 'duration': '120.5', 'bit_rate': '5000000', 'r_frame_rate': '30/1'},
                {'codec_type': 'audio', 'codec_name': 'aac', 'sample_rate': '44100', 'channels': 2, 'channel_layout': 'stereo', 'duration': '120.5', 'bit_rate': '128000'}
            ],
            'format': {'tags': {'artist': 'Test Artist', 'title': 'Test Title'}}
        }
        expected_metadata = {
            'video_streams': [{'codec_name': 'h264', 'width': 1920, 'height': 1080, 'duration': 120.5, 'bit_rate': 5000000, 'frame_rate': 30.0}],
            'audio_streams': [{'codec_name': 'aac', 'sample_rate': 44100, 'channels': 2, 'channel_layout': 'stereo', 'duration': 120.5, 'bit_rate': 128000}],
            'format_tags': {'artist': 'Test Artist', 'title': 'Test Title'}
        }
        self.assertEqual(extract_media_metadata(self.dummy_file_path, 'video/mp4'), expected_metadata)

    @patch('semantic_analyzer.os.path.exists', return_value=True)
    def test_extract_media_unsupported_mime(self, mock_exists):
        self.assertIsNone(extract_media_metadata(self.dummy_file_path, 'image/jpeg'))

    @patch('semantic_analyzer.os.path.exists', return_value=True)
    @patch('semantic_analyzer.ffmpeg.probe')
    @patch('builtins.print')
    def test_extract_media_ffmpeg_error_general(self, mock_print, mock_ffmpeg_probe, mock_exists):
        mock_ffmpeg_probe.side_effect = ffmpeg.Error("cmd", stdout=b"", stderr=b"ffmpeg general error")
        result = extract_media_metadata(self.dummy_file_path, 'video/mp4')
        self.assertIsNone(result)
        self.assertTrue(any("ffmpeg error probing" in call.args[0] for call in mock_print.call_args_list))
        self.assertFalse(any("CRITICAL: ffmpeg/ffprobe not found" in call.args[0] for call in mock_print.call_args_list))


    @patch('semantic_analyzer.os.path.exists', return_value=True)
    @patch('semantic_analyzer.ffmpeg.probe')
    @patch('builtins.print')
    def test_extract_media_ffmpeg_not_found_error(self, mock_print, mock_ffmpeg_probe, mock_exists):
        error_instance = ffmpeg.Error(cmd="ffprobe", stdout=b"", stderr=b"No such file or directory ffprobe")
        mock_ffmpeg_probe.side_effect = error_instance

        result = extract_media_metadata(self.dummy_file_path, 'video/mp4')
        self.assertIsNone(result)
        self.assertTrue(any("CRITICAL: ffmpeg/ffprobe not found" in call.args[0] for call in mock_print.call_args_list))


    @patch('semantic_analyzer.os.path.exists', return_value=True)
    @patch('semantic_analyzer.ffmpeg.probe')
    def test_extract_media_no_streams_no_tags(self, mock_ffmpeg_probe, mock_exists):
        mock_ffmpeg_probe.return_value = {'streams': [], 'format': {'tags': {}}}
        self.assertIsNone(extract_media_metadata(self.dummy_file_path, 'video/mp4'))


class TestGenerateTags(unittest.TestCase):
    def test_mime_type_tag(self):
        tags = generate_tags("application/pdf", None, None, None)
        self.assertIn("mime_application_pdf", tags)
        tags_error = generate_tags("Error: File not found", None, None, None)
        self.assertIn("mime_error_file_not_found", tags_error)

    def test_text_content_tags(self):
        text = "This is a test document about project finance and reporting. Report Q1 results. Finance is key."
        tags = generate_tags("text/plain", text, None, None)
        self.assertIn("text_finance", tags)
        self.assertIn("text_report", tags)
        self.assertTrue(any(t.startswith("text_") for t in tags))
        self.assertNotIn("text_this", tags)
        self.assertNotIn("text_is", tags)
        self.assertNotIn("text_q1", tags)

    def test_image_feature_tags(self):
        features_medium = {
            'dimensions': {'height': 1080, 'width': 1920, 'channels': 3},
            'average_color_bgr': [100.0, 150.0, 200.0]
        }
        tags_medium = generate_tags("image/jpeg", None, features_medium, None)
        self.assertIn("image_dim_1920x1080", tags_medium)
        self.assertIn("avg_color_b_100", tags_medium)
        self.assertIn("avg_color_g_150", tags_medium)
        self.assertIn("avg_color_r_200", tags_medium)
        self.assertIn("image_medium_brightness", tags_medium)

        features_dark = {
            'dimensions': {'height': 480, 'width': 640},
            'average_color_bgr': [10.0, 20.0, 30.0]
        }
        tags_dark = generate_tags("image/png", None, features_dark, None)
        self.assertIn("image_dim_640x480", tags_dark)
        self.assertIn("image_dark", tags_dark)

        features_bright = {
            'dimensions': {'height': 768, 'width': 1024, 'channels': 1},
            'average_color_bgr': [220.0, 220.0, 220.0]
        }
        tags_bright = generate_tags("image/bmp", None, features_bright, None)
        self.assertIn("image_dim_1024x768", tags_bright)
        self.assertIn("image_bright", tags_bright)

    def test_media_metadata_tags(self):
        metadata = {
            'video_streams': [{'codec_name': 'h264', 'width': 1920, 'height': 1080, 'duration': 120.5}],
            'audio_streams': [{'codec_name': 'aac', 'channels': 2, 'sample_rate': '44100'}],
            'format_tags': {'artist': 'Cool Artist', 'album': 'Great Album!', 'genre': 'Pop Rock'}
        }
        tags = generate_tags("video/mp4", None, None, metadata)
        self.assertIn("video_codec_h264", tags)
        self.assertIn("video_res_1080p", tags)
        self.assertIn("audio_codec_aac", tags)
        self.assertIn("audio_stereo", tags)
        self.assertIn("media_artist_coolartist", tags)
        self.assertIn("media_album_greatalbum", tags)
        self.assertIn("media_genre_poprock", tags)

    def test_combined_tags_and_uniqueness_sorting(self):
        text = "Invoice for services rendered by ACME Corp. Invoice again. Rendered services."
        image_features = {'dimensions': {'height': 800, 'width': 600}, 'average_color_bgr': [50,50,50]}
        media_metadata = {'format_tags': {'title': 'My Video'}}

        tags = generate_tags("application/pdf", text, image_features, media_metadata, top_n_keywords=3)

        # Expected tags after review:
        # Top 3 from text: invoice, services, rendered
        expected_tags_subset = [
            "avg_color_b_50",
            "avg_color_g_50",
            "avg_color_r_50",
            "image_dark",
            "image_dim_600x800",
            "media_title_myvideo",
            "mime_application_pdf",
            "text_invoice",
            "text_rendered", # Added this back
            "text_services",
        ]

        for etag in expected_tags_subset:
            self.assertIn(etag, tags)

        self.assertEqual(len([t for t in tags if t == "text_invoice"]), 1)
        self.assertEqual(tags, sorted(tags))
        self.assertFalse(any(t.startswith("video_") for t in tags))
        self.assertFalse(any(t.startswith("audio_") for t in tags))

if __name__ == '__main__':
    # Ensure mockable exception types are available on imported modules if not fully mocked
    # This helps if the test environment doesn't have the actual libraries,
    # but semantic_analyzer.py still needs to be imported.
    if not hasattr(ffmpeg, 'Error') or not inspect.isclass(ffmpeg.Error):
        class MockFFmpegError(Exception): pass
        ffmpeg.Error = MockFFmpegError
    if not hasattr(cv2, 'error') or not inspect.isclass(cv2.error):
        class MockCv2Error(Exception): pass
        cv2.error = MockCv2Error

    unittest.main()
