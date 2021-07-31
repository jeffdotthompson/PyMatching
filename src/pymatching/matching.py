# Copyright 2020 Oscar Higgott

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#      http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import warnings
from typing import Union, List, Set, Tuple, Dict

import matplotlib.cbook
import numpy as np
import networkx as nx
import scipy
from scipy.sparse import csc_matrix

from pymatching._cpp_mwpm import (exact_matching, local_matching,
                                  MatchingGraph)


def _find_boundary_nodes(graph: nx.Graph):
    """Find all boundary nodes in G

    Find the boundary nodes in G, each of which have the attribute
    `is_boundary' set to `True'. Return the indices of the 
    boundary nodes.

    Parameters
    ----------
    graph : NetworkX graph
        The matching graph.

    Returns
    -------
    set of int
        The indices of the boundary nodes in G.
    """
    return {i for i, attr in graph.nodes(data=True)
            if attr.get("is_boundary", False)}


class Matching:
    """A class for constructing matching graphs and decoding using the minimum-weight perfect matching decoder

    The Matching class provides most of the core functionality of PyMatching. 
    A PyMatching object can be constructed from the :math:`Z` or 
    :math:`X` check matrix of the quantum code, given as a `scipy.sparse` 
    matrix or `numpy.ndarray`, along with additional argument specifying the 
    edge weights, error probabilities and number of repetitions.
    Alternatively, a Matching object can be constructed from a NetworkX 
    graph, with node and edge attributes used to specify edge weights,
    qubit ids, boundaries and error probabilities.
    """
    def __init__(self,
                 H: Union[scipy.sparse.spmatrix, np.ndarray, nx.Graph, List[List[int]]]=None,
                 spacelike_weights: Union[float, np.ndarray]=None,
                 error_probabilities: Union[float, np.ndarray]=None,
                 repetitions: int=None,
                 timelike_weights: float=None,
                 measurement_error_probability: float=None,
                 precompute_shortest_paths: bool=False
                 ):
        r"""Constructor for the Matching class

        Parameters
        ----------
        H : `scipy.spmatrix` or `numpy.ndarray` or `networkx.Graph` object, optional
            The quantum code to be decoded with minimum-weight perfect
            matching, given either as a binary check matrix (scipy sparse 
            matrix or numpy.ndarray), or as a matching graph (NetworkX graph).
            If `H` is given as a NetworkX graph with `M` nodes, each node 
            `m` in `H` should be an integer :math:`0<m<M-1`, and each node should 
            be unique. Each edge in the NetworkX graph can have optional 
            attributes ``qubit_id``, ``weight`` and ``error_probability``. 
            ``qubit_id`` should be an int or a set of ints. If there 
            are :math:`N` qubits then the union of all ints in the ``qubit_id`` 
            attributes in the graph should be the integers :math:`0\ldots N-1`.
            Note that the ``qubit_id`` attribute can instead be used to store the indices
            of logical observables flipped by an error on the corresponding edge
            (e.g. a frame change in an error instruction in a stim detector error model).
            If there are N logical observables, they should again be numbered :math:`0\ldots N-1`.
            Each ``weight`` attribute should be a non-negative float. If 
            every edge is assigned an error_probability between zero and one, 
            then the ``add_noise`` method can be used to simulate noise and 
            flip edges independently in the graph. By default, None
        spacelike_weights : float or numpy.ndarray, optional
            If `H` is given as a scipy or numpy array, `spacelike_weights` gives the weights
            of edges in the matching graph. By default None, in which case 
            all weights are set to 1.0
        error_probabilities : float or numpy.ndarray, optional
            The probabilities with which an error occurs on each qubit. If a 
            single float is given, the same error probability is used for each 
            qubit. If a numpy.ndarray of floats is given, it must have a 
            length equal to the number of qubits. This parameter is only 
            needed for the Matching.add_noise method, and not for decoding. 
            By default None
        repetitions : int, optional
            The number of times the stabiliser measurements are repeated, if 
            the measurements are noisy. This option is only used if `H` is 
            provided as a check matrix, not a NetworkX graph. By default None
        timelike_weights : float, optional
            If `H` is given as a scipy or numpy array and `repetitions>1`, 
            `timelike_weights` gives the weight of timelike edges. By default 
            None, in which case all weights are set to 1.0
        measurement_error_probability : float, optional
            If `H` is given as a scipy or numpy array and `repetitions>1`, 
            gives the probability of a measurement error to be used for 
            the add_noise method. By default None
        precompute_shortest_paths : bool, optional
            It is almost always recommended to leave this as False. If 
            the exact matching is used for decoding (setting 
            `num_neighbours=None` in `decode`), then setting this option
            to True will precompute the all-pairs shortest paths.
            By default False
            """
        self.matching_graph = MatchingGraph()
        if H is None:
            return
        if not isinstance(H, nx.Graph):
            try:
                H = csc_matrix(H)
                self.load_from_check_matrix(H, spacelike_weights, error_probabilities,
                                            repetitions, timelike_weights, measurement_error_probability)
            except TypeError:
                raise TypeError("H must be a NetworkX graph or convertible "
                                "to a scipy.csc_matrix")
        else:
            self.load_from_networkx(H)
        if precompute_shortest_paths:
            self.matching_graph.compute_all_pairs_shortest_paths()

    def load_from_networkx(self, G: nx.Graph) -> None:
        r"""
        Load a matching graph from a NetworkX graph

        Parameters
        ----------
        G : networkx.Graph
            If `G` has `M` nodes, each node
            `m` in `G` should be an integer :math:`0<m<M-1`, and each node should
            be unique. Each edge in the NetworkX graph can have optional
            attributes ``qubit_id``, ``weight`` and ``error_probability``.
            ``qubit_id`` should be an int or a set of ints. If there
            are :math:`N` qubits then the union of all ints in the ``qubit_id``
            attributes in the graph should be the integers :math:`0\ldots N-1`.
            Note that the ``qubit_id`` attribute can instead be used to store the indices
            of logical observables flipped by an error on the corresponding edge
            (e.g. a frame change in an error instruction in a stim detector error model).
            If there are N logical observables, they should again be numbered :math:`0\ldots N-1`.
            Each ``weight`` attribute should be a non-negative float. If
            every edge is assigned an error_probability between zero and one,
            then the ``add_noise`` method can be used to simulate noise and
            flip edges independently in the graph.
        """

        if not isinstance(G, nx.Graph):
            raise TypeError("G must be a NetworkX graph")
        boundary = _find_boundary_nodes(G)
        num_nodes = G.number_of_nodes()
        all_qubits = set()
        g = MatchingGraph(self.num_detectors, boundary)
        for (u, v, attr) in G.edges(data=True):
            u, v = int(u), int(v)
            if u >= num_nodes or v>= num_nodes:
                raise ValueError("Every node id must be less "\
                                 "than the number of nodes, but edge "\
                                 "({},{}) was present.".format(u,v))
            qubit_id = attr.get("qubit_id", set())
            if isinstance(qubit_id, (int, np.integer)):
                qubit_id = {int(qubit_id)} if qubit_id != -1 else set()
            else:
                try:
                    qubit_id = set(qubit_id)
                    if not all(isinstance(q, (int, np.integer)) for q in qubit_id):
                        raise ValueError("qubit_id must be a set of ints, not {}".format(qubit_id))
                except:
                    raise ValueError(
                        "qubit_id property must be an int or a set of int"\
                        " (or convertible to a set), not {}".format(qubit_id))
            all_qubits = all_qubits | qubit_id
            weight = attr.get("weight", 1) # Default weight is 1 if not provided
            if weight < 0:
                raise ValueError("Weights cannot be negative.")
            e_prob = attr.get("error_probability", -1)
            g.add_edge(u, v, qubit_id, weight, e_prob, 0<=e_prob<=1)
        self.matching_graph = g
        if max(all_qubits, default=-1) != len(all_qubits) - 1:
            raise ValueError(
                "The maximum qubit id ({}) should equal the number of qubits ({}) "\
                "minus one.".format(max(all_qubits, default=0), len(all_qubits))
            )

    def load_from_check_matrix(self,
                               H: Union[scipy.sparse.spmatrix, np.ndarray, List[List[int]]],
                               spacelike_weights: Union[float, np.ndarray]=None,
                               error_probabilities: Union[float, np.ndarray]=None,
                               repetitions: int=None,
                               timelike_weights: float=None,
                               measurement_error_probability: float=None
                               ) -> None:
        """
        Load a matching graph from a check matrix

        Parameters
        ----------
        H : `scipy.spmatrix` or `numpy.ndarray`
            The quantum code to be decoded with minimum-weight perfect
            matching, given as a binary check matrix (scipy sparse
            matrix or numpy.ndarray)
        spacelike_weights : float or numpy.ndarray, optional
            The weights of edges in the matching graph.
            By default None, in which case all weights are set to 1.0
        error_probabilities : float or numpy.ndarray, optional
            The probabilities with which an error occurs on each qubit. If a
            single float is given, the same error probability is used for each
            qubit. If a numpy.ndarray of floats is given, it must have a
            length equal to the number of qubits. This parameter is only
            needed for the Matching.add_noise method, and not for decoding.
            By default None
        repetitions : int, optional
            The number of times the stabiliser measurements are repeated, if
            the measurements are noisy. By default None
        timelike_weights : float, optional
            If `repetitions>1`, `timelike_weights` gives the weight of
            timelike edges. By default None, in which case all
            weights are set to 1.0
        measurement_error_probability : float, optional
            If `repetitions>1`, gives the probability of a measurement
            error to be used for the add_noise method. By default None
        """
        try:
            H = csc_matrix(H)
        except TypeError:
            raise TypeError("H must be convertible to a scipy.csc_matrix")
        unique_elements = np.unique(H.data)
        if len(unique_elements) > 1 or unique_elements[0] != 1:
            raise ValueError("Nonzero elements in the parity check matrix" \
                             " must be 1, not {}.".format(unique_elements))
        H = H.astype(np.uint8)
        num_edges = H.shape[1]
        weights = 1.0 if spacelike_weights is None else spacelike_weights
        if isinstance(weights, (int, float)):
            weights = np.array([weights]*num_edges).astype(float)
        weights = np.asarray(weights)
        if error_probabilities is None:
            error_probabilities = np.array([-1] * num_edges)
        elif isinstance(error_probabilities, (int, float)):
            error_probabilities = np.array([error_probabilities] * num_edges)
        column_weights = np.asarray(H.sum(axis=0))[0]
        unique_column_weights = np.unique(column_weights)
        if np.setdiff1d(unique_column_weights, np.array([1, 2])).size > 0:
            raise ValueError("Each qubit must be contained in either " \
                             "1 or 2 check operators, not {}".format(unique_column_weights))
        H.eliminate_zeros()
        H.sort_indices()
        num_qubits = H.shape[1]

        if weights.shape[0] != num_qubits:
            raise ValueError("Weights array must have num_qubits elements")
        if np.any(weights < 0.):
            raise ValueError("All weights must be non-negative.")

        timelike_weights = 1.0 if timelike_weights is None else timelike_weights
        repetitions = 1 if repetitions is None else repetitions
        p_meas = measurement_error_probability if measurement_error_probability is not None else -1
        boundary = {H.shape[0] * repetitions} if 1 in unique_column_weights else set()
        self.matching_graph = MatchingGraph(H.shape[0] * repetitions, boundary=boundary)
        for t in range(repetitions):
            for i in range(len(H.indptr) - 1):
                s, e = H.indptr[i:i + 2]
                v1 = H.indices[s] + H.shape[0] * t
                v2 = H.indices[e - 1] + H.shape[0] * t if e - s == 2 else next(iter(boundary))
                self.matching_graph.add_edge(v1, v2, {i}, weights[i],
                                               error_probabilities[i], error_probabilities[i] >= 0)
        for t in range(repetitions - 1):
            for i in range(H.shape[0]):
                self.matching_graph.add_edge(i + t * H.shape[0], i + (t + 1) * H.shape[0],
                                               set(), timelike_weights, p_meas, p_meas >= 0)

    @property
    def num_qubits(self) -> int:
        return self.matching_graph.get_num_qubits()
    
    @property
    def boundary(self) -> Set[int]:
        """Return the indices of the boundary nodes

        Returns
        -------
        set of int
            The indices of the boundary nodes
        """
        return self.matching_graph.get_boundary()

    @property
    def num_nodes(self) -> int:
        return self.matching_graph.get_num_nodes()

    @property
    def num_detectors(self) -> int:
        return self.num_nodes - len(self.boundary)
    
    def decode(self,
               z: np.ndarray,
               num_neighbours: int=30,
               return_weight: bool=False
               ) -> Union[np.ndarray, Tuple[np.ndarray, int]]:
        """Decode the syndrome `z` using minimum-weight perfect matching

        If the parity of `z` is odd, then an arbitrarily chosen boundary node in
        ``self.boundary`` is flipped, and all other stabiliser and 
        boundary nodes are left unchanged.

        Parameters
        ----------
        z : numpy.ndarray
            A binary syndrome vector to decode. The number of elements in 
            `z` should equal the number of nodes in the matching graph. If 
            `z` is a 1D array, then `z[i]` is the syndrome at node `i` of 
            the matching graph. If `z` is 2D then `z[i,j]` is the difference 
            (modulo 2) between the (noisy) measurement of stabiliser `i` in time 
            step `j+1` and time step `j` (for the case where `repetitions>1`).
        num_neighbours : int, optional
            Number of closest neighbours of each matching graph node to consider 
            when decoding. If `num_neighbours` is set (as it is by default), 
            then the local matching decoder in the Appendix of 
            https://arxiv.org/abs/2010.09626 is used, and `num_neighbours` 
            corresponds to the parameter `m` in the paper. It is recommended 
            to leave `num_neighbours` set to at least 20.
            If `num_neighbours is None`, then instead full matching is 
            performed, with the all-pairs shortest paths precomputed and 
            cached the first time it is used. Since full matching is more 
            memory intensive, it is not recommended to be used for matching graphs 
            with more than around 10,000 nodes, and is only faster than 
            local matching for matching graphs with less than around 1,000 
            nodes. By default 30
        return_weight : bool, optional
            If `return_weight==True`, the sum of the weights of the edges in the 
            minimum weight perfect matching is also returned. By default False

        Returns
        -------
        numpy.ndarray
            A 1D numpy array of ints giving the minimum-weight correction 
            operator. The number of elements equals the number of qubits, 
            and an element is 1 if the corresponding qubit should be flipped, 
            and otherwise 0.

        float
            Present only if `return_weight==True`.
            The sum of the weights of the edges in the minimum-weight perfect 
            matching.

        """
        try:
            z = np.array(z, dtype=np.uint8)
        except:
            raise TypeError("Syndrome must be of type numpy.ndarray or "\
                            "convertible to numpy.ndarray, not {}".format(z))
        if len(z.shape) == 1 and (self.num_detectors <= z.shape[0]
                                  <= self.num_detectors + len(self.boundary)):
            defects = z.nonzero()[0]
        elif len(z.shape) == 2 and z.shape[0]*z.shape[1] == self.num_detectors:
            times, checks = z.T.nonzero()
            defects = times*z.shape[0] + checks
        else:
            raise ValueError("The shape ({}) of the syndrome vector z is not valid.".format(z.shape))
        if num_neighbours is None:
            res = exact_matching(self.matching_graph, defects, return_weight)
        else:
            res = local_matching(self.matching_graph, defects, num_neighbours, return_weight)
        if return_weight:
            return res.correction, res.weight
        else:
            return res.correction
    
    def add_noise(self) -> Union[Tuple[np.ndarray, np.ndarray], None]:
        """Add noise by flipping edges in the matching graph with
        a probability given by the error_probility edge attribute.
        The ``error_probability`` must be set for all edges for this 
        method to run, otherwise it returns `None`.
        All boundary nodes are always given a 0 syndrome.

        Returns
        -------
        numpy.ndarray of dtype int
            Noise vector (binary numpy int array of length self.num_qubits)
        numpy.ndarray of dtype int
            Syndrome vector (binary numpy int array of length 
            self.num_detectors if there is no boundary, or self.num_detectors+len(self.boundary)
            if there are boundary nodes)
        """
        if not self.matching_graph.all_edges_have_error_probabilities():
            return None
        return self.matching_graph.add_noise()
    
    def edges(self) -> List[Tuple[int, int, Dict]]:
        """Edges of the matching graph

        Returns a list of edges of the matching graph. Each edge is a 
        tuple `(source, target, attr)` where `source` and `target` are ints corresponding to the 
        indices of the source and target nodes, and `attr` is a dictionary containing the 
        attributes of the edge.
        The dictionary `attr` has keys `qubit_id` (a set of ints), `weight` (the weight of the edge, 
        set to 1.0 if not specified), and `error_probability` 
        (the error probability of the edge, set to -1 if not specified).

        Returns
        -------
        List of (int, int, dict) tuples
            A list of edges of the matching graph
        """
        edata = self.matching_graph.get_edges()
        return [(e[0], e[1], {
            'qubit_id': e[2].qubit_ids,
            'weight': e[2].weight,
            'error_probability': e[2].error_probability
            }) for e in edata]
    
    def to_networkx(self) -> nx.Graph:
        """Convert to NetworkX graph

        Returns a NetworkX graph corresponding to the matching graph. Each edge 
        has attributes `qubit_ids`, `weight` and `error_probability` and each node has 
        the attribute `is_boundary`.

        Returns
        -------
        NetworkX.Graph
            NetworkX Graph corresponding to the matching graph
        """
        G = nx.Graph()
        G.add_edges_from(self.edges())
        boundary = self.boundary
        for i in range(G.number_of_nodes()):
            is_boundary = i in boundary
            G.nodes[i]['is_boundary'] = is_boundary
        return G
    
    def draw(self) -> None:
        """Draw the matching graph using matplotlib

        Draws the matching graph as a matplotlib graph. Stabiliser nodes are 
        filled grey and boundary nodes are filled white. The line thickness of each 
        edge is determined from its weight (with min and max thicknesses of 0.2 pts
        and 2 pts respectively).
        Note that you may need to call `plt.figure()` before and `plt.show()` after calling 
        this function.
        """
        # Ignore matplotlib deprecation warnings from networkx.draw_networkx
        warnings.filterwarnings("ignore",category=matplotlib.cbook.mplDeprecation)
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        G = self.to_networkx()
        pos=nx.spectral_layout(G, weight=None)
        c = "#bfbfbf"
        ncolors = ['w' if n[1]['is_boundary'] else c for n in G.nodes(data=True)]
        nx.draw_networkx_nodes(G, pos=pos, node_color=ncolors, edgecolors=c)
        nx.draw_networkx_labels(G, pos=pos)
        weights=np.array([e[2]['weight'] for e in G.edges(data=True)])
        normalised_weights = 0.2+2*weights/np.max(weights)
        nx.draw_networkx_edges(G, pos=pos, width=normalised_weights)

        def qid_to_str(qid):
            if len(qid) == 0:
                return ""
            elif len(qid) == 1:
                return str(qid.pop())
            else:
                return str(qid)
        edge_labels = {(s, t): qid_to_str(d['qubit_id']) for (s,t,d) in G.edges(data=True)}
        nx.draw_networkx_edge_labels(G, pos=pos, edge_labels=edge_labels)

    def __repr__(self) -> str:
        N = self.num_qubits
        M = self.num_detectors
        B = len(self.boundary)
        E = self.matching_graph.get_num_edges()
        return "<pymatching.Matching object with "\
               "{} qubit{}, {} detector{}, "\
               "{} boundary node{}, "\
               "and {} edge{}>".format(N, 's' if N != 1 else '',
               M, 's' if M != 1 else '', B, 's' if B != 1 else '',
               E, 's' if E != 1 else '')
