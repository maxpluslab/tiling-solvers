//! The edge compatibility graph: which piece edge may lie flush against which
//! fixed edge, decided once from the edge signatures.
//!
//! Nodes are the oriented edges of the tray and of every piece. An arc from a
//! fixed edge to a piece edge says that nothing known before the search rules
//! the contact out. The pose a contact gives is not stored: it depends on where
//! the fixed edge ends up, and is computed when a corner asks for it.
//!
//! Without roofs the signatures rule out nothing between different pieces: the
//! pieces need not meet edge to edge, so lengths prove nothing, and whether an
//! angle fits depends on the corner. With roofs they do: two roofs can only be
//! continuous along a shared edge if their slopes along it agree, and the two
//! edges run in opposite directions, so the slopes along them must cancel.
//!
//! If the pieces are known to meet edge to edge (see [`Meeting`]), lengths do
//! prove something: a piece edge lies against the whole of one edge of one
//! other piece, or on the tray. Arcs can then ask for equal lengths and, with
//! roofs, equal heights at both ends; and an edge with no such partner on any
//! other piece can only lie on the tray.
//!
//! The same signatures say which pieces are interchangeable and which
//! placements of one piece are the same placement, so that the search does not
//! count one assembly many times.

use tiling_core::{Roof, Vec2};

use crate::contact::{ContactTolerance, EdgeRef};
use crate::edges::{EdgeSignature, edge_signatures};

/// What is assumed about how pieces meet, and which consequences are used.
///
/// The default assumes nothing: a vertex of one piece may lie anywhere along
/// an edge of another. With `edge_to_edge`, no vertex of a piece lies strictly
/// inside an edge of another piece, as in a puzzle cut from a polyhedral
/// complex. That is an assumption about the assembly sought, not a pruning
/// rule: it changes what a search can find. The other two fields are pruning
/// rules that follow from it, and are ignored without it.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct Meeting {
    /// Refuse a placement that puts a vertex strictly inside another piece's edge.
    pub edge_to_edge: bool,
    /// Let a piece edge lie against a piece edge only if the two are equally
    /// long and, with roofs, equally high at both ends.
    pub equal_edges: bool,
    /// Keep a piece edge that no other piece's edge can lie against on the tray.
    pub wall_edges: bool,
}

impl Meeting {
    /// The assumption with both of its rules.
    pub fn edge_to_edge() -> Meeting {
        Meeting {
            edge_to_edge: true,
            equal_edges: true,
            wall_edges: true,
        }
    }

    pub(crate) fn uses_equal_edges(&self) -> bool {
        self.edge_to_edge && self.equal_edges
    }

    pub(crate) fn uses_wall_edges(&self) -> bool {
        self.edge_to_edge && self.wall_edges
    }
}

/// A piece as the candidate generator sees it: a local polygon and its roof, if any.
#[derive(Debug, Clone, PartialEq)]
pub struct Shape {
    pub polygon: Vec<Vec2>,
    pub roof: Option<Roof>,
}

#[derive(Debug, Clone)]
pub struct EdgeGraph {
    signatures: Vec<Vec<EdgeSignature>>,
    /// Index of each piece's first edge among all piece edges.
    offsets: Vec<usize>,
    edge_count: usize,
    /// `arcs[fixed * edge_count + mover]` over piece edges. Tray edges accept every piece edge.
    arcs: Vec<bool>,
    /// For each piece edge, whether some edge of another piece could lie
    /// against the whole of it: slopes cancelling, equal length, equal heights.
    partnered: Vec<bool>,
    classes: Vec<usize>,
    /// For each piece, the turn that takes its class's first piece onto it.
    turns: Vec<f64>,
    symmetry: Vec<usize>,
}

fn same_edge(a: &EdgeSignature, b: &EdgeSignature, tolerance: &ContactTolerance) -> bool {
    let near = |x: Option<f64>, y: Option<f64>, tol: f64| match (x, y) {
        (None, None) => true,
        (Some(x), Some(y)) => (x - y).abs() <= tol,
        _ => false,
    };
    (a.length - b.length).abs() <= tolerance.length
        && (a.angle_start - b.angle_start).abs() <= tolerance.angle
        && near(a.height_start, b.height_start, tolerance.length)
        && near(a.slope_along, b.slope_along, tolerance.slope)
        && near(a.slope_across, b.slope_across, tolerance.slope)
}

/// Whether `b`, started `shift` edges later, has the same edges as `a` all the way round.
fn same_cycle(
    a: &[EdgeSignature],
    b: &[EdgeSignature],
    shift: usize,
    tolerance: &ContactTolerance,
) -> bool {
    let n = a.len();
    n == b.len() && (0..n).all(|k| same_edge(&a[k], &b[(k + shift) % n], tolerance))
}

/// How many rotations about its centroid map a convex polygon onto itself:
/// 1 for a polygon with no symmetry, 4 for a square.
pub fn rotation_order(polygon: &[Vec2], tolerance: &ContactTolerance) -> usize {
    let cycle = edge_signatures(polygon, None);
    (0..cycle.len())
        .filter(|&s| same_cycle(&cycle, &cycle, s, tolerance))
        .count()
}

impl EdgeGraph {
    /// The graph when nothing is assumed about how pieces meet.
    pub fn build(shapes: &[Shape], tolerance: &ContactTolerance) -> EdgeGraph {
        EdgeGraph::build_for(shapes, tolerance, false)
    }

    /// With `equal_edges`, an arc also needs the two edges to be equally long
    /// and, with roofs, equally high at both ends: what holds for every
    /// contact between pieces that meet edge to edge.
    pub fn build_for(
        shapes: &[Shape],
        tolerance: &ContactTolerance,
        equal_edges: bool,
    ) -> EdgeGraph {
        let signatures: Vec<Vec<EdgeSignature>> = shapes
            .iter()
            .map(|s| edge_signatures(&s.polygon, s.roof.as_ref()))
            .collect();
        let mut offsets = Vec::with_capacity(shapes.len());
        let mut edge_count = 0;
        for piece in &signatures {
            offsets.push(edge_count);
            edge_count += piece.len();
        }

        // The mover's edge runs the other way, so its start meets the fixed edge's end.
        let level = |x: Option<f64>, y: Option<f64>| match (x, y) {
            (Some(x), Some(y)) => (x - y).abs() <= tolerance.height,
            _ => true,
        };
        let whole = |a: &EdgeSignature, b: &EdgeSignature| {
            (a.length - b.length).abs() <= tolerance.length
                && level(a.height_start, b.height_end)
                && level(a.height_end, b.height_start)
        };
        let mut partnered = vec![false; edge_count];
        let mut arcs = vec![false; edge_count * edge_count];
        for (p, fixed) in signatures.iter().enumerate() {
            for (q, mover) in signatures.iter().enumerate() {
                if p == q {
                    continue;
                }
                for (i, a) in fixed.iter().enumerate() {
                    for (j, b) in mover.iter().enumerate() {
                        let fits = match (a.slope_along, b.slope_along) {
                            // The mover's edge runs the other way along the same line.
                            (Some(x), Some(y)) => (x + y).abs() <= tolerance.slope,
                            _ => true,
                        };
                        let fits_whole = fits && whole(a, b);
                        partnered[offsets[p] + i] |= fits_whole;
                        arcs[(offsets[p] + i) * edge_count + offsets[q] + j] =
                            if equal_edges { fits_whole } else { fits };
                    }
                }
            }
        }

        // A piece's class is the first piece with the same cycle of edges.
        // With it goes the turn that lays that piece, as stored, onto this one as
        // stored: congruent pieces need not be stored the same way round.
        let direction = |polygon: &[Vec2], edge: usize| {
            let (a, b) = (polygon[edge], polygon[(edge + 1) % polygon.len()]);
            (b[1] - a[1]).atan2(b[0] - a[0])
        };
        let (classes, turns): (Vec<usize>, Vec<f64>) = (0..shapes.len())
            .map(|p| {
                (0..p)
                    .find_map(|q| {
                        (0..signatures[p].len())
                            .find(|&s| same_cycle(&signatures[q], &signatures[p], s, tolerance))
                            .map(|s| {
                                let turn = direction(&shapes[p].polygon, s)
                                    - direction(&shapes[q].polygon, 0);
                                (q, turn)
                            })
                    })
                    .unwrap_or((p, 0.0))
            })
            .unzip();
        let symmetry = signatures
            .iter()
            .map(|cycle| {
                (0..cycle.len())
                    .filter(|&s| same_cycle(cycle, cycle, s, tolerance))
                    .count()
            })
            .collect();

        EdgeGraph {
            signatures,
            offsets,
            edge_count,
            arcs,
            partnered,
            classes,
            turns,
            symmetry,
        }
    }

    /// Whether edge `edge` of `piece` may lie flush against `fixed`.
    pub fn compatible(&self, fixed: EdgeRef, piece: usize, edge: usize) -> bool {
        match fixed {
            EdgeRef::Tray { .. } => true,
            EdgeRef::Piece {
                piece: other,
                edge: other_edge,
            } => {
                self.arcs[(self.offsets[other] + other_edge) * self.edge_count
                    + self.offsets[piece]
                    + edge]
            }
        }
    }

    /// Whether some edge of another piece could lie against the whole of this
    /// one. An edge without such a partner lies on the tray in every assembly
    /// whose pieces meet edge to edge.
    pub fn has_partner(&self, piece: usize, edge: usize) -> bool {
        self.partnered[self.offsets[piece] + edge]
    }

    /// Number of piece edges.
    pub fn edge_count(&self) -> usize {
        self.edge_count
    }

    /// Number of arcs between piece edges.
    pub fn arc_count(&self) -> usize {
        self.arcs.iter().filter(|&&arc| arc).count()
    }

    pub fn signatures(&self, piece: usize) -> &[EdgeSignature] {
        &self.signatures[piece]
    }

    /// The lowest-numbered piece congruent to `piece`, roof included. Pieces of
    /// one class are interchangeable.
    pub fn class(&self, piece: usize) -> usize {
        self.classes[piece]
    }

    /// The turn about its centroid that takes the first piece of this piece's
    /// class, as stored, onto this piece as stored. Zero for that first piece.
    /// For a piece with a symmetry it is one of several such turns.
    pub fn turn_from_class(&self, piece: usize) -> f64 {
        self.turns[piece]
    }

    /// How many rotations map `piece` onto itself, roof included: 1 for a
    /// piece with no symmetry, 4 for a level square. Vertices `0..n / symmetry`
    /// then stand for all of them.
    pub fn symmetry(&self, piece: usize) -> usize {
        self.symmetry[piece]
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::polygon::{centroid, transform};
    use crate::testing::{TOL, convex_polygon, pose};
    use proptest::prelude::*;
    use tiling_core::Pose;

    fn bare(polygon: &[Vec2]) -> Shape {
        Shape {
            polygon: polygon.to_vec(),
            roof: None,
        }
    }

    fn rectangle(w: f64, h: f64) -> Vec<Vec2> {
        vec![
            [-w / 2.0, -h / 2.0],
            [w / 2.0, -h / 2.0],
            [w / 2.0, h / 2.0],
            [-w / 2.0, h / 2.0],
        ]
    }

    #[test]
    fn without_roofs_every_edge_of_another_piece_is_a_possible_mate() {
        let shapes = [
            bare(&rectangle(2.0, 1.0)),
            bare(&[[0.0, 0.0], [3.0, 0.0], [0.0, 3.0]]),
        ];
        let graph = EdgeGraph::build(&shapes, &TOL);
        assert_eq!(graph.edge_count(), 7);
        // 4 * 3 arcs each way, none within a piece.
        assert_eq!(graph.arc_count(), 24);
        assert!(graph.compatible(EdgeRef::Piece { piece: 0, edge: 2 }, 1, 1));
        assert!(!graph.compatible(EdgeRef::Piece { piece: 0, edge: 2 }, 0, 1));
        assert!(graph.compatible(EdgeRef::Tray { edge: 5 }, 0, 0));
    }

    #[test]
    fn roofs_leave_only_edges_whose_slopes_cancel() {
        // Two unit squares, each rising 0.5 per mm towards its own +x side. Along x the
        // slopes are +0.5 on the bottom edge and -0.5 on the top; the sides are level.
        let roof = Some(Roof {
            z0: 5.0,
            gx: 0.5,
            gy: 0.0,
        });
        let square = rectangle(1.0, 1.0);
        let shapes = [
            Shape {
                polygon: square.clone(),
                roof,
            },
            Shape {
                polygon: square,
                roof,
            },
        ];
        let graph = EdgeGraph::build(&shapes, &TOL);
        let fixed = |edge| EdgeRef::Piece { piece: 0, edge };
        // Bottom (+0.5) mates with top (-0.5) and with nothing else.
        assert_eq!(
            (0..4)
                .map(|e| graph.compatible(fixed(0), 1, e))
                .collect::<Vec<_>>(),
            [false, false, true, false]
        );
        // A level side mates with either level side.
        assert_eq!(
            (0..4)
                .map(|e| graph.compatible(fixed(1), 1, e))
                .collect::<Vec<_>>(),
            [false, true, false, true]
        );
        // Bottom-top, top-bottom and the four pairings of sides: 6 from each piece to the other.
        assert_eq!(graph.arc_count(), 12);
    }

    #[test]
    fn congruent_pieces_share_a_class_whatever_their_orientation() {
        let a = rectangle(2.0, 1.0);
        let turned = transform(
            &a,
            &Pose {
                x: 0.0,
                y: 0.0,
                theta: 0.7,
            },
        );
        // The same rectangle listed from another vertex.
        let shifted: Vec<Vec2> = (0..4).map(|i| turned[(i + 1) % 4]).collect();
        let shapes = [
            bare(&a),
            bare(&rectangle(2.0, 1.5)),
            bare(&shifted),
            bare(&rectangle(1.0, 2.0)),
        ];
        let graph = EdgeGraph::build(&shapes, &TOL);
        assert_eq!(
            (0..4).map(|p| graph.class(p)).collect::<Vec<_>>(),
            [0, 1, 0, 0]
        );
    }

    #[test]
    fn symmetry_counts_the_rotations_that_keep_a_piece() {
        let scalene = [[0.0, 0.0], [4.0, 0.0], [0.0, 3.0]];
        let equilateral = [[0.0, 0.0], [2.0, 0.0], [1.0, 3f64.sqrt()]];
        let shapes = [
            bare(&scalene),
            bare(&rectangle(2.0, 1.0)),
            bare(&rectangle(1.0, 1.0)),
            bare(&equilateral),
        ];
        let graph = EdgeGraph::build(&shapes, &TOL);
        assert_eq!(
            (0..4).map(|p| graph.symmetry(p)).collect::<Vec<_>>(),
            [1, 2, 4, 3]
        );
    }

    #[test]
    fn a_roof_can_break_a_symmetry_and_tell_twins_apart() {
        let square = rectangle(1.0, 1.0);
        let sloped = |gx, gy| Shape {
            polygon: square.clone(),
            roof: Some(Roof { z0: 5.0, gx, gy }),
        };
        let shapes = [
            sloped(0.0, 0.0),
            sloped(0.5, 0.0),
            // The same roof as the second piece, seen a quarter turn on.
            sloped(0.0, 0.5),
            sloped(0.25, 0.0),
        ];
        let graph = EdgeGraph::build(&shapes, &TOL);
        assert_eq!(
            (0..4).map(|p| graph.symmetry(p)).collect::<Vec<_>>(),
            [4, 1, 1, 1]
        );
        assert_eq!(
            (0..4).map(|p| graph.class(p)).collect::<Vec<_>>(),
            [0, 1, 1, 3]
        );
    }

    proptest! {
        #[test]
        fn a_moved_copy_is_in_the_same_class(polygon in convex_polygon(), motion in pose(), shift in 0usize..8) {
            let turned = transform(&polygon, &Pose { x: 0.0, y: 0.0, theta: motion.theta });
            let n = turned.len();
            let relisted: Vec<Vec2> = (0..n).map(|i| turned[(i + shift) % n]).collect();
            let [cx, cy] = centroid(&relisted);
            prop_assert!(cx.hypot(cy) < 1e-9);
            let graph = EdgeGraph::build(&[bare(&polygon), bare(&relisted)], &TOL);
            prop_assert_eq!(graph.class(1), 0);
            prop_assert_eq!(graph.symmetry(0), graph.symmetry(1));
            // The order of a rotation group of an n-gon divides n.
            prop_assert_eq!(n % graph.symmetry(0), 0);
        }
    }
}
