"""
test_logo_filter.py - Verification test suite for graphic logo filtering & image validation
"""

import os
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

import tempfile
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.abspath("."))

from crawler.image_enricher import is_logo_or_graphic, is_valid_photo


def run_logo_filter_tests():
    print("=" * 70)
    print("🚀 LAUNCHING LOGO FILTER & IMAGE VALIDATION TEST SUITE")
    print("=" * 70)

    test_dir = tempfile.mkdtemp(prefix="trot_logo_test_")

    try:
        # TEST 1: Synthetic Logo "THE FACT" (Red background + White text)
        print("\n[TEST 1] Testing flat logo filter on synthetic THE FACT logo...")
        logo_path = os.path.join(test_dir, "the_fact_logo.png")
        img_logo = Image.new("RGB", (500, 500), (220, 25, 25))
        draw = ImageDraw.Draw(img_logo)
        draw.rectangle([50, 150, 450, 350], fill=(220, 25, 25))
        draw.text((120, 220), "THE FACT", fill=(255, 255, 255))
        img_logo.save(logo_path)

        is_logo1 = is_logo_or_graphic(img_logo)
        is_valid1 = is_valid_photo(logo_path)
        print(f"  -> THE FACT logo: is_logo_or_graphic={is_logo1}, is_valid_photo={is_valid1}")
        assert is_logo1 is True, "Expected THE FACT logo to be flagged as graphic logo!"
        assert is_valid1 is False, "Expected THE FACT logo to fail is_valid_photo!"

        # TEST 2: Synthetic Logo "X" (Orange background + White X)
        print("\n[TEST 2] Testing flat logo filter on synthetic X logo...")
        logo2_path = os.path.join(test_dir, "x_logo.png")
        img_logo2 = Image.new("RGB", (500, 500), (235, 75, 20))
        draw2 = ImageDraw.Draw(img_logo2)
        draw2.text((200, 200), "X", fill=(255, 255, 255))
        img_logo2.save(logo2_path)

        is_logo2 = is_logo_or_graphic(img_logo2)
        is_valid2 = is_valid_photo(logo2_path)
        print(f"  -> X logo: is_logo_or_graphic={is_logo2}, is_valid_photo={is_valid2}")
        assert is_logo2 is True, "Expected X logo to be flagged as graphic logo!"
        assert is_valid2 is False, "Expected X logo to fail is_valid_photo!"

        # TEST 3: Real Photo Simulation (High color variance / natural textures)
        print("\n[TEST 3] Testing real photo simulation...")
        photo_path = os.path.join(test_dir, "real_photo.jpg")
        import numpy as np
        arr = np.random.randint(40, 220, (600, 500, 3), dtype=np.uint8)
        img_photo = Image.fromarray(arr)
        img_photo.save(photo_path, "JPEG", quality=90)

        is_logo3 = is_logo_or_graphic(img_photo)
        is_valid3 = is_valid_photo(photo_path)
        print(f"  -> Real photo: is_logo_or_graphic={is_logo3}, is_valid_photo={is_valid3}")
        assert is_logo3 is False, "Real photo should NOT be flagged as graphic logo!"
        assert is_valid3 is True, "Real photo should pass is_valid_photo!"

        print("\n==================================================")
        print("ALL LOGO FILTER TESTS PASSED WITH 0 ERRORS!")
        print("==================================================")

    finally:
        import shutil
        shutil.rmtree(test_dir, ignore_errors=True)


if __name__ == "__main__":
    run_logo_filter_tests()
