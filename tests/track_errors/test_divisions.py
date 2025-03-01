import networkx as nx
import numpy as np
import pytest
from traccuracy import NodeAttr, TrackingGraph
from traccuracy.matchers._matched import Matched
from traccuracy.track_errors.divisions import (
    _classify_divisions,
    _correct_shifted_divisions,
    _evaluate_division_events,
    _get_pred_by_t,
    _get_succ_by_t,
)

from ..test_utils import get_division_graphs


class DummyMatched(Matched):
    def compute_mapping(self):
        return []


@pytest.fixture
def g():
    """
    1_0 -- 1_1 -- 1_2 -- 1_3
                         3_3
    2_0 -- 2_1 -- 2_2 -<
                         4_3
    """
    g = nx.DiGraph()
    g.add_edge("1_0", "1_1")
    g.add_edge("1_1", "1_2")
    g.add_edge("1_2", "1_3")

    g.add_edge("2_0", "2_1")
    g.add_edge("2_1", "2_2")

    # node 2 divides into 3 and 4 in frame 3
    g.add_edge("2_2", "3_3")
    g.add_edge("2_2", "4_3")

    # Set node attributes
    attrs = {}
    for node in g.nodes:
        attrs[node] = {"t": int(node[-1:]), "x": 0, "y": 0}
    nx.set_node_attributes(g, attrs)

    return g


def test_classify_divisions_tp(g):
    # Define mapper assuming all nodes match
    mapper = [(n, n) for n in g.nodes]
    g_gt = TrackingGraph(g.copy())
    g_pred = TrackingGraph(g.copy())
    matched_data = DummyMatched(g_gt, g_pred)
    matched_data.mapping = mapper

    # Test true positive
    _classify_divisions(matched_data)

    assert len(g_gt.get_nodes_with_flag(NodeAttr.FN_DIV)) == 0
    assert len(g_pred.get_nodes_with_flag(NodeAttr.FP_DIV)) == 0
    assert NodeAttr.TP_DIV in g_gt.nodes()["2_2"]
    assert NodeAttr.TP_DIV in g_pred.nodes()["2_2"]

    # Check division flag
    assert g_gt.division_annotations
    assert g_pred.division_annotations


def test_classify_divisions_fp(g):
    """
                         5_3
    1_0 -- 1_1 -- 1_2 -<
                         1_3
                         3_3
    2_0 -- 2_1 -- 2_2 -<
                         4_3
    """
    h = g.copy()
    # Add false positive division edge
    h.add_edge("1_2", "5_3")
    nx.set_node_attributes(h, {"5_3": {"t": 3, "x": 0, "y": 0}})
    mapper = [(n, n) for n in h.nodes]

    g_gt = TrackingGraph(g)
    g_pred = TrackingGraph(h)
    matched_data = DummyMatched(g_gt, g_pred)
    matched_data.mapping = mapper

    _classify_divisions(matched_data)

    assert len(g_gt.get_nodes_with_flag(NodeAttr.FN_DIV)) == 0
    assert NodeAttr.FP_DIV in g_pred.nodes()["1_2"]
    assert NodeAttr.TP_DIV in g_gt.nodes()["2_2"]
    assert NodeAttr.TP_DIV in g_pred.nodes()["2_2"]


def test_classify_divisions_fn(g):
    """
    1_0 -- 1_1 -- 1_2 -- 1_3
    2_0 -- 2_1 -- 2_2
    """
    # Remove daughters to create false negative
    h = g.copy()
    h.remove_nodes_from(["3_3", "4_3"])
    mapper = [(n, n) for n in h.nodes]

    g_gt = TrackingGraph(g)
    g_pred = TrackingGraph(h)
    matched_data = DummyMatched(g_gt, g_pred)
    matched_data.mapping = mapper

    _classify_divisions(matched_data)

    assert len(g_pred.get_nodes_with_flag(NodeAttr.FP_DIV)) == 0
    assert len(g_gt.get_nodes_with_flag(NodeAttr.TP_DIV)) == 0
    assert NodeAttr.FN_DIV in g_gt.nodes()["2_2"]


@pytest.fixture
def straight_graph():
    g = nx.DiGraph()
    for t in range(2, 10):
        g.add_edge(f"1_{t}", f"1_{t+1}")

    # Set node attributes
    attrs = {}
    for node in g.nodes:
        attrs[node] = {"t": int(node[-1:]), "x": 0, "y": 0}
    nx.set_node_attributes(g, attrs)

    return g


def test__get_pred_by_t(straight_graph):
    # Linear graph with node id 1 from frame 2-10
    g = TrackingGraph(straight_graph)

    # Predecessor available
    start_frame = 10
    target_frame = 5
    node = _get_pred_by_t(g, f"1_{start_frame}", start_frame - target_frame)
    assert node == f"1_{target_frame}"

    # Predecessor does not exist
    start_frame = 10
    target_frame = 1
    node = _get_pred_by_t(g, f"1_{start_frame}", start_frame - target_frame)
    assert node is None


def test__get_succ_by_t():
    _, g2, _ = get_division_graphs()
    g2 = TrackingGraph(g2)

    # Find 2 frames forward correctly
    start_node = "2_2"
    delta_t = 2
    end_node = "2_4"
    node = _get_succ_by_t(g2, start_node, delta_t)
    assert node == end_node

    # 3 frames forward returns None
    start_node = "2_2"
    delta_t = 3
    end_node = None
    node = _get_succ_by_t(g2, start_node, delta_t)
    assert node == end_node


class Test_correct_shifted_divisions:
    def test_no_change(self):
        # Early division in gt
        g_pred, g_gt, mapper = get_division_graphs()
        g_gt.nodes["1_1"][NodeAttr.FN_DIV] = True
        g_pred.nodes["1_3"][NodeAttr.FP_DIV] = True

        matched_data = DummyMatched(TrackingGraph(g_gt), TrackingGraph(g_pred))
        matched_data.mapping = mapper

        # buffer of 1, no change
        new_matched = _correct_shifted_divisions(matched_data, n_frames=1)
        ng_pred = new_matched.pred_graph
        ng_gt = new_matched.gt_graph

        assert ng_pred.nodes()["1_3"][NodeAttr.FP_DIV] is True
        assert ng_gt.nodes()["1_1"][NodeAttr.FN_DIV] is True
        assert len(ng_gt.get_nodes_with_flag(NodeAttr.TP_DIV)) == 0

    def test_fn_early(self):
        # Early division in gt
        g_pred, g_gt, mapper = get_division_graphs()
        g_gt.nodes["1_1"][NodeAttr.FN_DIV] = True
        g_pred.nodes["1_3"][NodeAttr.FP_DIV] = True

        matched_data = DummyMatched(TrackingGraph(g_gt), TrackingGraph(g_pred))
        matched_data.mapping = mapper

        # buffer of 3, corrections
        new_matched = _correct_shifted_divisions(matched_data, n_frames=3)
        ng_pred = new_matched.pred_graph
        ng_gt = new_matched.gt_graph

        assert ng_pred.nodes()["1_3"][NodeAttr.FP_DIV] is False
        assert ng_gt.nodes()["1_1"][NodeAttr.FN_DIV] is False
        assert ng_pred.nodes()["1_3"][NodeAttr.TP_DIV] is True
        assert ng_gt.nodes()["1_1"][NodeAttr.TP_DIV] is True

    def test_fp_early(self):
        # Early division in pred
        g_gt, g_pred, mapper = get_division_graphs()
        g_pred.nodes["1_1"][NodeAttr.FP_DIV] = True
        g_gt.nodes["1_3"][NodeAttr.FN_DIV] = True

        matched_data = DummyMatched(TrackingGraph(g_gt), TrackingGraph(g_pred))
        matched_data.mapping = mapper

        # buffer of 3, corrections
        new_matched = _correct_shifted_divisions(matched_data, n_frames=3)
        ng_pred = new_matched.pred_graph
        ng_gt = new_matched.gt_graph

        assert ng_pred.nodes()["1_1"][NodeAttr.FP_DIV] is False
        assert ng_gt.nodes()["1_3"][NodeAttr.FN_DIV] is False
        assert ng_pred.nodes()["1_1"][NodeAttr.TP_DIV] is True
        assert ng_gt.nodes()["1_3"][NodeAttr.TP_DIV] is True


def test_evaluate_division_events():
    g_gt, g_pred, mapper = get_division_graphs()
    frame_buffer = (0, 1, 2)

    matched_data = DummyMatched(TrackingGraph(g_gt), TrackingGraph(g_pred))
    matched_data.mapping = mapper

    results = _evaluate_division_events(matched_data, frame_buffer=frame_buffer)

    assert np.all([isinstance(k, int) for k in results.keys()])
