""" Subpackage for loading tracking data into memory

This subpackage contains functions for loading ground
truth or tracking method outputs into memory as TrackingGraph objects.
Each loading function must return one TrackingGraph object which has a
track graph and optionally contains a corresponding segmentation.
"""
from ._ctc import load_ctc_data

__all__ = ["load_ctc_data"]
