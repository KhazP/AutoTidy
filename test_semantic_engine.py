import unittest
import os
import shutil
import tempfile
from pathlib import Path

# Add project root to sys.path to allow importing semantic_engine
# This might be needed if running tests directly and the project structure isn't automatically recognized
import sys
project_root = Path(__file__).resolve().parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Now import the module to be tested
try:
    from semantic_engine import (
        get_file_type,
        extract_text_from_file,
        analyze_image,
        get_media_metadata,
        generate_tags_from_text,
        NLP_MODEL # To check if it loaded
    )
except ImportError as e:
    print(f"Failed to import from semantic_engine: {e}")
    print("Ensure semantic_engine.py is in the same directory or sys.path is correctly set.")
    # Define dummy functions if import fails, so tests can still be discovered, though they will fail.
    def get_file_type(fp): return None
    def extract_text_from_file(fp): return None
    def analyze_image(fp): return None
    def get_media_metadata(fp): return None
    def generate_tags_from_text(txt): return []
    NLP_MODEL = None


# Helper to create dummy image (requires OpenCV)
def _create_dummy_image(path, width=10, height=10, color=(0, 0, 255)): # Red BGR
    try:
        import cv2
        import numpy as np
        img = np.zeros((height, width, 3), dtype=np.uint8)
        img[:,:] = color
        cv2.imwrite(str(path), img)
        return True
    except ImportError:
        print("OpenCV not installed, cannot create dummy image for tests.")
        return False
    except Exception as e:
        print(f"Error creating dummy image {path}: {e}")
        return False

# Helper to create dummy audio (requires ffmpeg)
def _create_dummy_audio(path, duration=0.1): # Short duration for faster tests
    try:
        import ffmpeg
        (
            ffmpeg
            .input('anullsrc', format='lavfi', r='44100', t=str(duration))
            .output(str(path), acodec='mp3', audio_bitrate='16k') # Low bitrate
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True)
        )
        return True
    except ImportError:
        print("ffmpeg-python not installed, cannot create dummy audio for tests.")
        return False
    except ffmpeg.Error as e:
        print(f"ffmpeg error creating dummy audio {path}: {e.stderr.decode('utf8') if e.stderr else e}")
        return False
    except FileNotFoundError: # If ffmpeg executable is not found
        print(f"ffmpeg executable not found. Cannot create dummy audio {path}.")
        return False
    except Exception as e:
        print(f"General error creating dummy audio {path}: {e}")
        return False


class TestSemanticEngine(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp(prefix="autotidy_test_")
        print(f"Test directory created: {cls.test_dir}")

        # Create sample files
        cls.txt_file = Path(cls.test_dir) / "sample.txt"
        with open(cls.txt_file, "w") as f:
            f.write("This is a test. Hello world from AutoTidy tests.")

        cls.pdf_file_type_test = Path(cls.test_dir) / "sample_type.pdf" # For MIME type
        with open(cls.pdf_file_type_test, "wb") as f:
            f.write(b"%PDF-1.0\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n3 0 obj<</Type/Page/MediaBox[0 0 3 3]>>endobj\nxref\n0 4\n0000000000 65535 f\n0000000010 00000 n\n0000000059 00000 n\n0000000118 00000 n\ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n149\n%%EOF")

        cls.pdf_file_text_extract = Path(cls.test_dir) / "sample_text.pdf" # For text extraction
        try:
            from reportlab.pdfgen import canvas
            # Increased page size to ensure text fits
            c = canvas.Canvas(str(cls.pdf_file_text_extract), pagesize=(600,100))
            cls.pdf_text_content = "Hello PDF from ReportLab for AutoTidy."
            c.drawString(30, 30, cls.pdf_text_content)
            c.save()
        except ImportError:
            print("ReportLab not installed, cannot create text PDF for tests. Text extraction from PDF test will be limited.")
            # Create a simple PDF if reportlab is not available, though textract might not get text from it
            with open(cls.pdf_file_text_extract, "wb") as f:
                f.write(b"%PDF-1.0\n% Minimal PDF for testing existence")
            cls.pdf_text_content = None # Mark that we don't expect specific text


        cls.img_file = Path(cls.test_dir) / "sample.png"
        cls.img_created = _create_dummy_image(cls.img_file)

        cls.audio_file = Path(cls.test_dir) / "sample.mp3"
        cls.audio_created = _create_dummy_audio(cls.audio_file)

        cls.empty_file = Path(cls.test_dir) / "empty.dat"
        cls.empty_file.touch()

        cls.nlp_text = "Dr. Smith visited London and Paris. He met with a representative from Google LLC."


    @classmethod
    def tearDownClass(cls):
        print(f"Removing test directory: {cls.test_dir}")
        shutil.rmtree(cls.test_dir)

    def test_01_get_file_type(self):
        self.assertEqual(get_file_type(str(self.txt_file)), "text/plain")
        self.assertEqual(get_file_type(str(self.pdf_file_type_test)), "application/pdf")
        if self.img_created:
            self.assertEqual(get_file_type(str(self.img_file)), "image/png")
        if self.audio_created:
            # MIME for MP3 can be 'audio/mpeg' or 'audio/mp3'
            self.assertIn(get_file_type(str(self.audio_file)), ["audio/mpeg", "audio/mp3"])
        self.assertIn(get_file_type(str(self.empty_file)), ["application/octet-stream", "inode/x-empty"]) # More robust check
        self.assertIsNone(get_file_type("non_existent_file.xyz"))
        self.assertIsNone(get_file_type(self.test_dir)) # Should be None for a directory

    def test_02_extract_text_from_file(self):
        self.assertEqual(extract_text_from_file(str(self.txt_file)), "This is a test. Hello world from AutoTidy tests.")
        if self.pdf_text_content: # Only if PDF with text was successfully created
            extracted_pdf_text = extract_text_from_file(str(self.pdf_file_text_extract))
            self.assertIsNotNone(extracted_pdf_text)
            if extracted_pdf_text: # Check if textract managed to get something
                 self.assertIn(self.pdf_text_content, extracted_pdf_text)
        else: # If reportlab wasn't available, pdf_text_content is None
             # textract might return "" or None for a PDF it can't read text from
            pdf_text_output = extract_text_from_file(str(self.pdf_file_text_extract))
            self.assertTrue(pdf_text_output == "" or pdf_text_output is None,
                            "Expected empty string or None from minimal/empty PDF")

        text_output_empty = extract_text_from_file(str(self.empty_file))
        self.assertTrue(text_output_empty == "" or text_output_empty is None)

        if self.img_created:
             img_text_output = extract_text_from_file(str(self.img_file))
             self.assertTrue(img_text_output == "" or img_text_output is None)
        self.assertIsNone(extract_text_from_file("non_existent_file.xyz"))

    def test_03_analyze_image(self):
        if not self.img_created:
            self.skipTest("Dummy image not created (likely OpenCV missing). Skipping image analysis test.")

        result = analyze_image(str(self.img_file))
        self.assertIsNotNone(result, "analyze_image returned None for a valid image.")
        self.assertEqual(result["width"], 10)
        self.assertEqual(result["height"], 10)
        self.assertTrue(len(result["dominant_colors_bgr"]) > 0)
        is_red_dominant = False
        for color in result["dominant_colors_bgr"]: # K-means might find slight variations
            if abs(color[0] - 0) < 15 and abs(color[1] - 0) < 15 and abs(color[2] - 255) < 15:
                is_red_dominant = True
                break
        self.assertTrue(is_red_dominant, f"Dominant color red not found in {result['dominant_colors_bgr']}")

        self.assertIsNone(analyze_image(str(self.txt_file)))
        self.assertIsNone(analyze_image("non_existent_file.xyz"))

    def test_04_get_media_metadata(self):
        if not self.audio_created:
            self.skipTest("Dummy audio not created (likely ffmpeg missing). Skipping media metadata test.")

        result = get_media_metadata(str(self.audio_file))
        self.assertIsNotNone(result, "get_media_metadata returned None for a valid audio file.")
        self.assertIn("format", result)
        self.assertIn("streams", result)
        self.assertTrue(len(result["streams"]) > 0)
        self.assertIsInstance(float(result["format"].get("duration", "0")), float)
        self.assertAlmostEqual(float(result["format"].get("duration", "0")), 0.1, delta=0.09) # Increased delta slightly for ffmpeg variations


        self.assertIsNone(get_media_metadata(str(self.txt_file)))
        self.assertIsNone(get_media_metadata("non_existent_file.xyz"))

    def test_05_generate_tags_from_text(self):
        if not NLP_MODEL:
            self.skipTest("spaCy model not loaded. Skipping NLP tagging test.")

        tags = generate_tags_from_text(self.nlp_text)
        self.assertTrue(len(tags) > 0)
        expected_tags_subset = ["Dr. Smith", "London", "Paris", "Google LLC"]
        for tag in expected_tags_subset:
            self.assertIn(tag, tags, f"Expected tag '{tag}' not found in {tags}")

        self.assertEqual(generate_tags_from_text(""), [])
        self.assertEqual(generate_tags_from_text(None), [])

    def test_06_empty_file_handling(self):
        self.assertIn(get_file_type(str(self.empty_file)), ["application/octet-stream", "inode/x-empty"])

        text_output = extract_text_from_file(str(self.empty_file))
        self.assertTrue(text_output == "" or text_output is None)

        self.assertIsNone(analyze_image(str(self.empty_file)))
        self.assertIsNone(get_media_metadata(str(self.empty_file)))

        if NLP_MODEL: # Check if model loaded before testing generate_tags_from_text
            self.assertEqual(generate_tags_from_text(""), [])


if __name__ == '__main__':
    print(f"Attempting to run tests for semantic_engine.py. Current sys.path: {sys.path[0]}")
    if os.path.exists("semantic_engine.py"):
        print("Found semantic_engine.py in current directory.")
    else:
        print("semantic_engine.py not found in current directory. Ensure it's present or in PYTHONPATH.")

    unittest.main()
