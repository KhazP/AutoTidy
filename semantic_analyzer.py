import magic
import os
from tika import parser as tika_parser
import logging
import cv2
import numpy
import ffmpeg # Import ffmpeg

# Configure logging for Tika (optional, but good for debugging Tika issues)
logging.getLogger('tika').setLevel(logging.WARNING)
# Configure logging for ffmpeg (optional)
logging.getLogger('ffmpeg').setLevel(logging.WARNING)
# It's good practice to also check if cv2 is available and log if not,
# but for this exercise, we'll assume it installs correctly.

def get_file_type(file_path):
    """
    Determines the MIME type of a given file using python-magic.

    Args:
        file_path (str): The path to the file.

    Returns:
        str: The MIME type of the file, or an error message if detection fails.
    """
    if not os.path.exists(file_path):
        return "Error: File not found"
    if not os.path.isfile(file_path):
        return "Error: Not a file"
    try:
        mime_type = magic.from_file(file_path, mime=True)
        return mime_type
    except magic.MagicException as e:
        return f"Error: python-magic failed - {e}"
    except Exception as e:
        return f"Error: An unexpected error occurred - {e}"

# Define a list of MIME types that Tika is likely to handle for text extraction
SUPPORTED_DOCUMENT_MIME_TYPES = [
    'application/pdf',
    'application/msword', # .doc
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document', # .docx
    'application/vnd.ms-excel', # .xls
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', # .xlsx
    'application/vnd.ms-powerpoint', # .ppt
    'application/vnd.openxmlformats-officedocument.presentationml.presentation', # .pptx
    'application/rtf',
    'text/plain',
    'text/html',
    'application/xml',
    'text/xml', # Added for completeness, though application/xml is more common
    'application/vnd.oasis.opendocument.text', # .odt
    'application/vnd.oasis.opendocument.spreadsheet', # .ods
    'application/vnd.oasis.opendocument.presentation', # .odp
]

def extract_text_from_document(file_path: str, mime_type: str) -> str | None:
    """
    Extracts text content from a document using Apache Tika.

    Args:
        file_path (str): The path to the file.
        mime_type (str): The MIME type of the file.

    Returns:
        str | None: The extracted text content, or None if extraction is not possible,
                    not supported for the MIME type, or an error occurs.
    """
    if not os.path.exists(file_path):
        # This check is somewhat redundant if get_file_type is called first,
        # but good for a standalone function.
        # self.log_queue.put(f"DEBUG: Text extraction skipped: File not found {file_path}") # Assuming no direct log_queue access
        print(f"DEBUG: Text extraction skipped: File not found {file_path}") # Placeholder for logging
        return None

    if mime_type not in SUPPORTED_DOCUMENT_MIME_TYPES:
        # print(f"DEBUG: Text extraction skipped for MIME type: {mime_type} ({file_path})") # Placeholder for logging
        return None

    try:
        # Attempt to parse the file using Tika
        parsed = tika_parser.from_file(file_path)
        if parsed and 'content' in parsed and parsed['content']:
            text_content = parsed['content'].strip()
            if text_content: # Ensure content is not just whitespace
                return text_content
            else:
                # print(f"DEBUG: Text extraction from {file_path} resulted in empty or whitespace content.") # Placeholder
                return None
        else:
            # print(f"DEBUG: Tika parsing failed or returned no content for {file_path}.") # Placeholder
            return None
    except FileNotFoundError: # Should be caught by os.path.exists, but as a safeguard for tika specifics
        # print(f"ERROR: Tika reported FileNotFoundError for {file_path}") # Placeholder
        return None
    except Exception as e:
        # This catches various Tika errors, including server startup issues (No Tika server started),
        # password-protected files, corrupted files, etc.
        # print(f"WARNING: Tika failed to extract text from {file_path} (MIME: {mime_type}). Error: {e}") # Placeholder
        # Check if the error message indicates a Tika server issue (Java not found / Tika server not starting)
        if "tika server" in str(e).lower() or "java" in str(e).lower():
             print(f"CRITICAL: Tika server is not running or Java is not configured. Text extraction will be unavailable. Error: {e}")
        return None

# Define a list of MIME types that OpenCV is likely to handle for image feature extraction
SUPPORTED_IMAGE_MIME_TYPES = [
    'image/jpeg',
    'image/png',
    'image/bmp',
    'image/gif', # OpenCV can read GIFs, but typically only the first frame.
    'image/tiff',
    'image/webp',
]

def extract_image_features(file_path: str, mime_type: str) -> dict | None:
    """
    Extracts basic image features (dimensions, average color) using OpenCV.

    Args:
        file_path (str): The path to the image file.
        mime_type (str): The MIME type of the file.

    Returns:
        dict | None: A dictionary with image features, or None if extraction fails
                     or the MIME type is not supported.
    """
    if not os.path.exists(file_path):
        print(f"DEBUG: Image feature extraction skipped: File not found {file_path}") # Placeholder
        return None

    if mime_type not in SUPPORTED_IMAGE_MIME_TYPES:
        # print(f"DEBUG: Image feature extraction skipped for MIME type: {mime_type} ({file_path})") # Placeholder
        return None

    try:
        img = cv2.imread(file_path)
        if img is None:
            print(f"ERROR: OpenCV (cv2.imread) could not load image: {file_path}. Might be corrupted or unsupported format within MIME type.") # Placeholder
            return None

        height, width, *channels_tuple = img.shape
        channels = channels_tuple[0] if channels_tuple else 1 # Grayscale images might not have 3rd dimension

        average_color_bgr = [float(val) for val in cv2.mean(img)[:3]] # Ensure serializable (float)

        return {
            'dimensions': {'height': height, 'width': width, 'channels': channels},
            'average_color_bgr': average_color_bgr
        }
    except cv2.error as e:
        print(f"ERROR: OpenCV error processing {file_path} (MIME: {mime_type}): {e}") # Placeholder
        return None
    except Exception as e:
        print(f"ERROR: Unexpected error extracting image features from {file_path} (MIME: {mime_type}): {e}") # Placeholder
        return None

SUPPORTED_MEDIA_MIME_TYPES = [
    # Video formats
    'video/mp4',
    'video/x-matroska', # .mkv
    'video/x-msvideo',  # .avi
    'video/quicktime',  # .mov
    'video/x-flv',      # .flv
    'video/webm',
    'video/3gpp',
    'video/mpeg',
    # Audio formats
    'audio/mpeg',       # .mp3
    'audio/wav',        # .wav (raw PCM, often)
    'audio/aac',
    'audio/ogg',        # Vorbis
    'audio/flac',
    'audio/x-ms-wma',   # .wma
    'audio/opus',
]

def extract_media_metadata(file_path: str, mime_type: str) -> dict | None:
    """
    Extracts media metadata (video/audio streams, format tags) using ffmpeg-python.

    Args:
        file_path (str): The path to the media file.
        mime_type (str): The MIME type of the file.

    Returns:
        dict | None: A dictionary with media metadata, or None if extraction fails,
                     MIME type is not supported, or ffmpeg/ffprobe is not found.
    """
    if not os.path.exists(file_path):
        print(f"DEBUG: Media metadata extraction skipped: File not found {file_path}") # Placeholder
        return None

    if mime_type not in SUPPORTED_MEDIA_MIME_TYPES:
        # print(f"DEBUG: Media metadata extraction skipped for MIME type: {mime_type} ({file_path})") # Placeholder
        return None

    try:
        probe_data = ffmpeg.probe(file_path)

        metadata = {
            'video_streams': [],
            'audio_streams': [],
            'format_tags': {}
        }

        if 'streams' in probe_data:
            for stream in probe_data['streams']:
                if stream.get('codec_type') == 'video':
                    video_info = {
                        'codec_name': stream.get('codec_name'),
                        'width': stream.get('width'),
                        'height': stream.get('height'),
                        'duration': float(stream.get('duration', 0.0)) if stream.get('duration') else None, # Ensure float
                        'bit_rate': int(stream.get('bit_rate', 0)) if stream.get('bit_rate') else None, # Ensure int
                        'frame_rate': eval(stream.get('r_frame_rate', '0/1')) if stream.get('r_frame_rate') else None, # e.g. "24/1"
                    }
                    metadata['video_streams'].append(video_info)
                elif stream.get('codec_type') == 'audio':
                    audio_info = {
                        'codec_name': stream.get('codec_name'),
                        'sample_rate': int(stream.get('sample_rate', 0)) if stream.get('sample_rate') else None, # Ensure int
                        'channels': stream.get('channels'),
                        'channel_layout': stream.get('channel_layout'),
                        'duration': float(stream.get('duration', 0.0)) if stream.get('duration') else None, # Ensure float
                        'bit_rate': int(stream.get('bit_rate', 0)) if stream.get('bit_rate') else None, # Ensure int
                    }
                    metadata['audio_streams'].append(audio_info)

        if 'format' in probe_data and 'tags' in probe_data['format']:
            common_tags = ['artist', 'album', 'title', 'genre', 'date', 'composer', 'performer', 'comment']
            for tag_name in common_tags:
                if tag_name in probe_data['format']['tags']:
                    metadata['format_tags'][tag_name] = probe_data['format']['tags'][tag_name]
            # Optionally, add all other tags if any
            # for key, value in probe_data['format']['tags'].items():
            #    if key not in metadata['format_tags']: # Avoid overwriting common tags if logic changes
            #        metadata['format_tags'][key] = value


        # Return None if no substantial metadata was extracted (e.g. just empty lists and dict)
        if not metadata['video_streams'] and not metadata['audio_streams'] and not metadata['format_tags']:
            print(f"DEBUG: No substantial media metadata extracted for {file_path}") # Placeholder
            return None

        return metadata

    except ffmpeg.Error as e:
        # This can happen if ffmpeg/ffprobe is not installed/found, or file is invalid
        if "No such file or directory" in str(e) or "ffprobe" in str(e).lower():
             print(f"CRITICAL: ffmpeg/ffprobe not found or not executable. Media metadata extraction will be unavailable. Error: {e}")
        else:
             print(f"ERROR: ffmpeg error probing {file_path} (MIME: {mime_type}): {e}") # Placeholder
        return None
    except Exception as e:
        print(f"ERROR: Unexpected error extracting media metadata from {file_path} (MIME: {mime_type}): {e}") # Placeholder
        return None

# Define a small list of common English stop words
STOP_WORDS = set([
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "and", "or", "but", "if", "of", "to", "in", "on", "at", "by", "for",
    "with", "about", "against", "between", "into", "through", "during",
    "before", "after", "above", "below", "from", "up", "down", "out",
    "off", "over", "under", "again", "further", "then", "once", "here",
    "there", "when", "where", "why", "how", "all", "any", "both", "each",
    "few", "more", "most", "other", "some", "such", "no", "nor", "not",
    "only", "own", "same", "so", "than", "too", "very", "s", "t", "can",
    "will", "just", "don", "should", "now", "it", "its", "this", "that"
])

def generate_tags(mime_type: str, text_content: str | None,
                  image_features: dict | None, media_metadata: dict | None,
                  top_n_keywords: int = 5) -> list[str]:
    """
    Generates a list of descriptive tags based on input features.

    Args:
        mime_type (str): The MIME type of the file.
        text_content (str | None): Extracted text from the document.
        image_features (dict | None): Extracted features from an image.
        media_metadata (dict | None): Extracted metadata from a media file.
        top_n_keywords (int): Number of top keywords to extract from text.

    Returns:
        list[str]: A list of generated string tags.
    """
    tags = set() # Use a set to automatically handle duplicates, then convert to list

    # 1. Add MIME type tag
    if mime_type and not mime_type.startswith("Error:"):
        tags.add(f"mime_{mime_type.replace('/', '_')}")
    elif mime_type: # If it's an error string from get_file_type
        tags.add(f"mime_error_{mime_type.split(':')[-1].strip().replace(' ', '_').lower()}")


    # 2. Process text_content for keyword tags
    if text_content:
        try:
            words = [word for word in text_content.lower().split() if word.isalnum()]
            filtered_words = [word for word in words if word not in STOP_WORDS and len(word) >= 3]

            if filtered_words:
                from collections import Counter
                word_counts = Counter(filtered_words)
                for word, _ in word_counts.most_common(top_n_keywords):
                    tags.add(f"text_{word}")
        except Exception as e:
            print(f"Error processing text content for tags: {e}") # Placeholder

    # 3. Process image_features
    if image_features:
        try:
            if 'dimensions' in image_features:
                dims = image_features['dimensions']
                tags.add(f"image_dim_{dims.get('width',0)}x{dims.get('height',0)}")
            if 'average_color_bgr' in image_features:
                bgr = image_features['average_color_bgr']
                if len(bgr) == 3:
                    tags.add(f"avg_color_b_{int(bgr[0])}")
                    tags.add(f"avg_color_g_{int(bgr[1])}")
                    tags.add(f"avg_color_r_{int(bgr[2])}")
                    # Simple brightness/darkness based on average intensity
                    intensity = sum(bgr) / 3
                    if intensity < 85:
                        tags.add("image_dark")
                    elif intensity > 170:
                        tags.add("image_bright")
                    else:
                        tags.add("image_medium_brightness")

        except Exception as e:
            print(f"Error processing image features for tags: {e}") # Placeholder

    # 4. Process media_metadata
    if media_metadata:
        try:
            if media_metadata.get('video_streams'):
                for vs in media_metadata['video_streams'][:1]: # Process first video stream
                    if vs.get('codec_name'):
                        tags.add(f"video_codec_{vs['codec_name']}")
                    if vs.get('width') and vs.get('height'):
                        h = vs['height']
                        if h >= 2160: res_tag = "4k"
                        elif h >= 1080: res_tag = "1080p"
                        elif h >= 720: res_tag = "720p"
                        elif h >= 480: res_tag = "480p"
                        else: res_tag = f"{h}p"
                        tags.add(f"video_res_{res_tag}")

            if media_metadata.get('audio_streams'):
                for aus in media_metadata['audio_streams'][:1]: # Process first audio stream
                    if aus.get('codec_name'):
                        tags.add(f"audio_codec_{aus['codec_name']}")
                    if aus.get('channels'):
                        if aus['channels'] == 1: tags.add("audio_mono")
                        elif aus['channels'] == 2: tags.add("audio_stereo")
                        else: tags.add(f"audio_{aus['channels']}channels")


            if media_metadata.get('format_tags'):
                for key, value in media_metadata['format_tags'].items():
                    if value and isinstance(value, str) and len(value) < 50: # Basic sanity check
                        # Sanitize value for tag: lowercase, replace spaces with '_', keep alphanumeric
                        safe_value = ''.join(filter(str.isalnum, value.lower().replace(' ', '_')))
                        if safe_value:
                           tags.add(f"media_{key.lower()}_{safe_value}")
        except Exception as e:
            print(f"Error processing media metadata for tags: {e}") # Placeholder

    return sorted(list(tags))


if __name__ == '__main__':
    # Example Usage (for testing purposes)
    # Create a dummy file for testing
    test_file_path = "test_file.txt"
    with open(test_file_path, "w") as f:
        f.write("This is a test file.")

    print(f"File: {test_file_path}, MIME Type: {get_file_type(test_file_path)}")

    # Clean up the dummy file
    os.remove(test_file_path)

    # Test with a non-existent file
    non_existent_file = "non_existent_file.txt"
    print(f"File: {non_existent_file}, MIME Type: {get_file_type(non_existent_file)}")

    # Test with a directory (if possible, depends on OS and permissions)
    # Create a dummy directory for testing
    # test_dir_path = "test_dir"
    # if not os.path.exists(test_dir_path):
    #     os.makedirs(test_dir_path)
    # print(f"File: {test_dir_path}, MIME Type: {get_file_type(test_dir_path)}") # This would be "Error: Not a file"
    # if os.path.exists(test_dir_path):
    #     os.rmdir(test_dir_path)

    # Example for extract_text_from_document (requires a Tika server running and Java)
    # ... (previous __main__ content for text extraction) ...
    if os.path.exists(test_file_path): # Re-check as it might have been removed by previous test
        # This part of __main__ is mostly for get_file_type and extract_text_from_document
        # For extract_image_features, you'd need an actual image file.
        # Let's create a dummy image file for testing purposes if possible,
        # though creating meaningful image files programmatically without more libraries is complex.
        # We'll just demonstrate the call path.

        # Create a dummy png file (1x1 pixel black image) for testing extract_image_features
        dummy_image_path = "dummy_test_image.png"
        try:
            # Create a minimal valid PNG (1x1 black pixel)
            # PNG signature: \x89PNG\r\n\x1a\n
            # IHDR chunk: length 13, name IHDR, data (1x1 pixel, 8-bit depth, color type 0 (grayscale), no compression, no filter, no interlace)
            # IDAT chunk: length 2, name IDAT, data (compressed pixel data - for 1 black pixel, this can be simple)
            # IEND chunk: length 0, name IEND
            png_data = bytes([
                0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,  # PNG signature
                0x00, 0x00, 0x00, 0x0D, 0x49, 0x48, 0x44, 0x52,  # IHDR chunk
                0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,  # 1x1 pixel
                0x08, 0x00, 0x00, 0x00, 0x00, 0x90, 0x77, 0x53, 0xDE, # 8-bit depth, grayscale, CRC
                0x00, 0x00, 0x00, 0x0C, 0x49, 0x44, 0x41, 0x54,  # IDAT chunk (minimal data for 1 black pixel)
                0x78, 0x9C, 0x63, 0x00, 0x01, 0x00, 0x00, 0x05,  # x, c, c, nul, soh, nul, nul, etx
                0x00, 0x01, 0x0D, 0x0A, 0x2D, 0xB4, # CRC for IDAT
                0x00, 0x00, 0x00, 0x00, 0x49, 0x45, 0x4E, 0x44,  # IEND chunk
                0xAE, 0x42, 0x60, 0x82
            ])
            with open(dummy_image_path, "wb") as f:
                f.write(png_data)

            print(f"\nCreated dummy image: {dummy_image_path}")
            image_mime = get_file_type(dummy_image_path)
            print(f"File: {dummy_image_path}, MIME Type: {image_mime}")

            if image_mime and image_mime in SUPPORTED_IMAGE_MIME_TYPES:
                print(f"Attempting to extract image features from: {dummy_image_path}")
                features = extract_image_features(dummy_image_path, image_mime)
                if features:
                    print(f"Extracted image features: {features}")
                else:
                    print("No image features extracted or extraction failed.")
            else:
                print(f"MIME type {image_mime} not supported for feature extraction or error in get_file_type.")

        except Exception as e:
            print(f"Error during dummy image creation or processing: {e}")
        finally:
            if os.path.exists(dummy_image_path):
                os.remove(dummy_image_path)
                print(f"Cleaned up dummy image: {dummy_image_path}")

        # Original text file test (if it exists and wasn't cleaned up by image test)
        if os.path.exists(test_file_path):
            mime_text = get_file_type(test_file_path)
            if mime_text and not mime_text.startswith("Error:"):
                print(f"\nAttempting to extract text from: {test_file_path} (MIME: {mime_text})")
                extracted_text = extract_text_from_document(test_file_path, mime_text)
                if extracted_text:
                    print(f"Extracted text (first 100 chars): {extracted_text[:100]}")
                else:
                    print("No text extracted or extraction failed for text file.")
            else:
                print(f"Could not determine MIME type for {test_file_path} to test text extraction.")
            # Clean up the text file created at the start of __main__
            os.remove(test_file_path)
            print(f"Cleaned up text file: {test_file_path}")
        else:
            print(f"Text file {test_file_path} not found for final test phase (may have been cleaned up).")

    # Example for extract_media_metadata (requires ffmpeg/ffprobe in PATH)...
    # ... (previous __main__ tests for get_file_type, text, image, media extraction) ...
    # Ensure dummy files are cleaned up if they were created by previous tests in __main__
    # This is becoming complex, so ideally these would be proper unit tests.

    print("\n--- Tag Generation Test ---")
    sample_mime = "application/pdf"
    sample_text = "This is a test document about project finance and reporting. Report Q1 results."
    sample_image_features = {'dimensions': {'height': 1080, 'width': 1920, 'channels': 3}, 'average_color_bgr': [100.0, 150.0, 200.0]}
    sample_media_metadata = {
        'video_streams': [{'codec_name': 'h264', 'width': 1920, 'height': 1080, 'duration': 120.5}],
        'audio_streams': [{'codec_name': 'aac', 'sample_rate': 44100, 'channels': 2}],
        'format_tags': {'artist': 'Test Artist', 'title': 'Test Title'}
    }

    tags1 = generate_tags(sample_mime, sample_text, None, None)
    print(f"Tags (text only): {tags1}")

    tags2 = generate_tags("image/jpeg", None, sample_image_features, None)
    print(f"Tags (image only): {tags2}")

    tags3 = generate_tags("video/mp4", None, None, sample_media_metadata)
    print(f"Tags (media only): {tags3}")

    tags_combined = generate_tags("application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                  sample_text, sample_image_features, sample_media_metadata)
    print(f"Tags (combined, though not typical for one file): {tags_combined}")

    tags_error_mime = generate_tags("Error: File not found", None, None, None)
    print(f"Tags (error mime): {tags_error_mime}")

    # Cleanup any dummy files that might have been created in the full __main__ sequence
    if os.path.exists("test_file.txt"): os.remove("test_file.txt")
    if os.path.exists("dummy_test_image.png"): os.remove("dummy_test_image.png")
    if os.path.exists("dummy_video.mp4"): os.remove("dummy_video.mp4")
    print("Cleaned up any dummy files from __main__ tests.")
