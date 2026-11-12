//! A partial assembly, and the candidate interface over it.
//!
//! [`Assembly`] is the reversible state a contact-based search works on:
//! pieces are placed and taken back in stack order. Its [`frontier`] is the
//! list of corners of the uncovered region, [`propose`] gives the placements
//! that fill one corner, and [`check_placement`] measures any placement.
//!
//! # Why branching on one convex corner loses nothing
//!
//! Take a convex corner of the uncovered region: a free wedge at `V`, narrower
//! than a half turn, starting along a fixed edge. In any way of completing the
//! assembly with convex pieces, some piece `P` covers the points just inside
//! the wedge next to that edge. `P` is closed, so it contains `V`. `P` lies in
//! the uncovered region, so around `V` it stays within the wedge; being convex
//! and reaching the wedge's first side, it has a vertex at `V` and its edge
//! leaving `V` runs along that side. Its angle at `V` is at most the wedge's.
//!
//! So `P`'s placement is one of: an unplaced piece, one of its vertices whose
//! angle fits, that vertex at `V`, the edge leaving it along the wedge's first
//! side. [`propose`] generates exactly those. A search that picks any one
//! convex corner and tries every proposal for it therefore reaches every
//! completion, and an uncovered region always has a convex corner (its lowest
//! point is one).
//!
//! This is an argument about exact assemblies in exact arithmetic. The code
//! works in `f64` with [`ContactTolerance`], and its results are evidence, not
//! proof.
//!
//! [`frontier`]: Assembly::frontier
//! [`propose`]: Assembly::propose
//! [`check_placement`]: Assembly::check_placement

use std::fmt;

use tiling_core::{Pose, Vec2};

use crate::cavity::{Cavity, cavities};
use crate::contact::{ContactTolerance, Corner, EdgeRef, free_corners, pose_at_corner};
use crate::graph::{EdgeGraph, Meeting, Shape};
use crate::polygon::{is_convex_ccw, outside_depth, transform};
use crate::relief::{roof_height, seam_step};
use crate::sat::penetration_depth;

/// One way to put a piece down, and the contact that produced it.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct CandidatePlacement {
    pub piece: usize,
    pub pose: Pose,
    /// The piece's vertex at the corner; the edge leaving it is the one in contact.
    pub vertex: usize,
    /// The fixed edge the piece's edge lies against.
    pub contact: EdgeRef,
}

/// What a placement would do to the assembly.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct PlacementCheck {
    /// How far the piece reaches outside the target, in mm.
    pub outside: f64,
    /// Its deepest penetration into a placed piece, in mm; zero if it enters none.
    pub overlap: f64,
    /// The placed piece it enters deepest, if any.
    pub blocker: Option<usize>,
}

impl PlacementCheck {
    pub fn fits(&self, tolerance: &ContactTolerance) -> bool {
        self.outside <= tolerance.length && self.overlap <= tolerance.length
    }
}

/// Counts of the candidate work done so far. They are never reset by `undo`.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct CandidateStats {
    /// Placements generated from contacts.
    pub generated: u64,
    /// Of those, rejected for reaching outside the target.
    pub rejected_outside: u64,
    /// Of the rest, rejected for entering a placed piece.
    pub rejected_overlap: u64,
    /// Rejected because the roof would not meet a neighbour's: at the corner
    /// before the other checks, or along a shared edge after them. Always zero
    /// for pieces without roofs.
    pub rejected_roof: u64,
    /// Rejected for putting a vertex strictly inside an edge of a placed piece,
    /// or the reverse. Always zero unless pieces are assumed to meet edge to edge.
    pub rejected_junction: u64,
    /// Rejected for taking an edge that no other piece's edge can lie against
    /// off the tray. Always zero unless that rule is on.
    pub rejected_wall: u64,
}

/// Smallest axis-aligned box around a polygon, as `[min x, min y, max x, max y]`.
fn bounds(polygon: &[Vec2]) -> [f64; 4] {
    let mut b = [
        f64::INFINITY,
        f64::INFINITY,
        f64::NEG_INFINITY,
        f64::NEG_INFINITY,
    ];
    for p in polygon {
        b[0] = b[0].min(p[0]);
        b[1] = b[1].min(p[1]);
        b[2] = b[2].max(p[0]);
        b[3] = b[3].max(p[1]);
    }
    b
}

/// Whether a point of `vertices` lies on an edge of `polygon`, more than
/// `tolerance` from both of its ends.
fn vertex_inside_an_edge(vertices: &[Vec2], polygon: &[Vec2], tolerance: f64) -> bool {
    let n = polygon.len();
    vertices.iter().any(|v| {
        (0..n).any(|i| {
            let (a, b) = (polygon[i], polygon[(i + 1) % n]);
            let (dx, dy) = (b[0] - a[0], b[1] - a[1]);
            let length = dx.hypot(dy);
            let along = ((v[0] - a[0]) * dx + (v[1] - a[1]) * dy) / length;
            let off = ((v[0] - a[0]) * dy - (v[1] - a[1]) * dx) / length;
            off.abs() <= tolerance && along > tolerance && along < length - tolerance
        })
    })
}

/// Whether two boxes are further apart than `slack` along an axis.
fn apart(a: &[f64; 4], b: &[f64; 4], slack: f64) -> bool {
    a[2] + slack < b[0] || b[2] + slack < a[0] || a[3] + slack < b[1] || b[3] + slack < a[1]
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AssemblyError {
    /// The target (`None`) or a piece is not a strictly convex counter-clockwise polygon.
    NotConvex(Option<usize>),
    BadTolerance,
    NoSuchPiece(usize),
    AlreadyPlaced(usize),
}

impl fmt::Display for AssemblyError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            AssemblyError::NotConvex(None) => {
                write!(
                    f,
                    "the target is not a strictly convex counter-clockwise polygon"
                )
            }
            AssemblyError::NotConvex(Some(piece)) => write!(
                f,
                "piece {piece} is not a strictly convex counter-clockwise polygon"
            ),
            AssemblyError::BadTolerance => write!(f, "tolerances must be finite and positive"),
            AssemblyError::NoSuchPiece(piece) => write!(f, "there is no piece {piece}"),
            AssemblyError::AlreadyPlaced(piece) => write!(f, "piece {piece} is already placed"),
        }
    }
}

impl std::error::Error for AssemblyError {}

#[derive(Debug, Clone)]
pub struct Assembly {
    target: Vec<Vec2>,
    shapes: Vec<Shape>,
    graph: EdgeGraph,
    tolerance: ContactTolerance,
    meeting: Meeting,
    poses: Vec<Option<Pose>>,
    world: Vec<Option<Vec<Vec2>>>,
    boxes: Vec<[f64; 4]>,
    /// Placed pieces, oldest first.
    stack: Vec<usize>,
    stats: CandidateStats,
}

impl Assembly {
    /// An assembly in which nothing is assumed about how pieces meet.
    pub fn new(
        target: Vec<Vec2>,
        shapes: Vec<Shape>,
        tolerance: ContactTolerance,
    ) -> Result<Assembly, AssemblyError> {
        Assembly::meeting(target, shapes, tolerance, Meeting::default())
    }

    /// An assembly whose candidates respect `meeting`.
    pub fn meeting(
        target: Vec<Vec2>,
        shapes: Vec<Shape>,
        tolerance: ContactTolerance,
        meeting: Meeting,
    ) -> Result<Assembly, AssemblyError> {
        let positive = |v: f64| v.is_finite() && v > 0.0;
        if ![
            tolerance.length,
            tolerance.angle,
            tolerance.slope,
            tolerance.height,
        ]
        .into_iter()
        .all(positive)
        {
            return Err(AssemblyError::BadTolerance);
        }
        if !is_convex_ccw(&target) {
            return Err(AssemblyError::NotConvex(None));
        }
        if let Some(piece) = shapes.iter().position(|s| !is_convex_ccw(&s.polygon)) {
            return Err(AssemblyError::NotConvex(Some(piece)));
        }
        let graph = EdgeGraph::build_for(&shapes, &tolerance, meeting.uses_equal_edges());
        let count = shapes.len();
        Ok(Assembly {
            target,
            shapes,
            graph,
            tolerance,
            meeting,
            poses: vec![None; count],
            world: vec![None; count],
            boxes: vec![[0.0; 4]; count],
            stack: Vec::with_capacity(count),
            stats: CandidateStats::default(),
        })
    }

    pub fn target(&self) -> &[Vec2] {
        &self.target
    }

    pub fn piece_count(&self) -> usize {
        self.shapes.len()
    }

    pub fn shape(&self, piece: usize) -> &Shape {
        &self.shapes[piece]
    }

    pub fn graph(&self) -> &EdgeGraph {
        &self.graph
    }

    pub fn tolerance(&self) -> &ContactTolerance {
        &self.tolerance
    }

    pub fn stats(&self) -> CandidateStats {
        self.stats
    }

    /// Placed pieces, oldest first.
    pub fn placed(&self) -> &[usize] {
        &self.stack
    }

    pub fn pose(&self, piece: usize) -> Option<Pose> {
        self.poses.get(piece).copied().flatten()
    }

    /// A placed piece's polygon in the world.
    pub fn world(&self, piece: usize) -> Option<&[Vec2]> {
        self.world.get(piece)?.as_deref()
    }

    pub fn all_placed(&self) -> bool {
        self.stack.len() == self.shapes.len()
    }

    /// Put a piece down. Nothing is checked beyond the piece being free:
    /// whether it fits is [`Assembly::check_placement`]'s question.
    pub fn place(&mut self, piece: usize, pose: Pose) -> Result<(), AssemblyError> {
        if piece >= self.shapes.len() {
            return Err(AssemblyError::NoSuchPiece(piece));
        }
        if self.poses[piece].is_some() {
            return Err(AssemblyError::AlreadyPlaced(piece));
        }
        let world = transform(&self.shapes[piece].polygon, &pose);
        self.boxes[piece] = bounds(&world);
        self.world[piece] = Some(world);
        self.poses[piece] = Some(pose);
        self.stack.push(piece);
        Ok(())
    }

    /// Take back the most recent placement and say which piece it was.
    pub fn undo(&mut self) -> Option<usize> {
        let piece = self.stack.pop()?;
        self.poses[piece] = None;
        self.world[piece] = None;
        Some(piece)
    }

    /// Placed pieces in index order, with their polygons in the world.
    fn placed_polygons(&self) -> Vec<(usize, &[Vec2])> {
        self.world
            .iter()
            .enumerate()
            .filter_map(|(piece, world)| world.as_deref().map(|polygon| (piece, polygon)))
            .collect()
    }

    /// Every corner of the uncovered region, convex or not, in a fixed order.
    /// Empty exactly when the placed pieces cover the target.
    pub fn frontier(&self) -> Vec<Corner> {
        free_corners(&self.target, &self.placed_polygons(), &self.tolerance)
    }

    /// The separate parts of the uncovered region whose corners are `corners`,
    /// which must be this state's [`Assembly::frontier`]. `None` if they do not
    /// link up; see [`cavities`].
    pub fn cavities(&self, corners: &[Corner]) -> Option<Vec<Cavity>> {
        cavities(corners, &self.tolerance)
    }

    /// The largest step between the roof of `piece`, placed at `pose`, and the
    /// roofs of the placed pieces, along the stretches of edge it shares with
    /// them. Zero for a piece without a roof, or one that shares no edge.
    ///
    /// Two roofs are planes, so the step along a shared stretch is largest at
    /// one of its ends, and those are the only points measured.
    pub fn roof_step(&self, piece: usize, pose: &Pose) -> Result<f64, AssemblyError> {
        let shape = self
            .shapes
            .get(piece)
            .ok_or(AssemblyError::NoSuchPiece(piece))?;
        Ok(self.roof_step_of(piece, pose, &transform(&shape.polygon, pose)))
    }

    fn roof_step_of(&self, piece: usize, pose: &Pose, world: &[Vec2]) -> f64 {
        let Some(roof) = &self.shapes[piece].roof else {
            return 0.0;
        };
        let reach = bounds(world);
        let mut worst: f64 = 0.0;
        for &other in &self.stack {
            let Some(other_roof) = &self.shapes[other].roof else {
                continue;
            };
            if other == piece || apart(&reach, &self.boxes[other], self.tolerance.length) {
                continue;
            }
            let (Some(other_world), Some(other_pose)) = (&self.world[other], &self.poses[other])
            else {
                continue;
            };
            worst = worst.max(seam_step(
                world,
                roof,
                pose,
                other_world,
                other_roof,
                other_pose,
                self.tolerance.length,
            ));
        }
        worst
    }

    /// Whether `world` enters a placed piece by more than the length tolerance.
    fn enters_a_placed_piece(&self, world: &[Vec2]) -> bool {
        let reach = bounds(world);
        self.stack.iter().any(|&other| {
            !apart(&reach, &self.boxes[other], 0.0)
                && self.world[other].as_ref().is_some_and(|polygon| {
                    penetration_depth(world, polygon) > self.tolerance.length
                })
        })
    }

    /// Whether `world` and a placed piece meet in a T: a vertex of one strictly
    /// inside an edge of the other.
    fn makes_a_junction(&self, world: &[Vec2]) -> bool {
        let reach = bounds(world);
        let tolerance = self.tolerance.length;
        self.stack.iter().any(|&other| {
            !apart(&reach, &self.boxes[other], tolerance)
                && self.world[other].as_ref().is_some_and(|polygon| {
                    vertex_inside_an_edge(world, polygon, tolerance)
                        || vertex_inside_an_edge(polygon, world, tolerance)
                })
        })
    }

    /// Whether `world`, a placement of `piece`, has an edge off the tray's
    /// boundary that no other piece's edge could lie against.
    fn strands_an_edge(&self, piece: usize, world: &[Vec2]) -> bool {
        let n = world.len();
        let tolerance = self.tolerance.length;
        let on_the_tray = |a: Vec2, b: Vec2| {
            let m = self.target.len();
            (0..m).any(|j| {
                let (s, e) = (self.target[j], self.target[(j + 1) % m]);
                let (dx, dy) = (e[0] - s[0], e[1] - s[1]);
                let length = dx.hypot(dy);
                let off = |p: Vec2| ((p[0] - s[0]) * dy - (p[1] - s[1]) * dx) / length;
                off(a).abs() <= tolerance && off(b).abs() <= tolerance
            })
        };
        (0..n).any(|i| {
            !self.graph.has_partner(piece, i) && !on_the_tray(world[i], world[(i + 1) % n])
        })
    }

    /// Measure a placement of `piece` against the target and the other placed pieces.
    pub fn check_placement(
        &self,
        piece: usize,
        pose: &Pose,
    ) -> Result<PlacementCheck, AssemblyError> {
        let shape = self
            .shapes
            .get(piece)
            .ok_or(AssemblyError::NoSuchPiece(piece))?;
        Ok(self.check_polygon(piece, &transform(&shape.polygon, pose)))
    }

    fn check_polygon(&self, piece: usize, world: &[Vec2]) -> PlacementCheck {
        let mut overlap = 0.0;
        let mut blocker = None;
        for (other, polygon) in self.placed_polygons() {
            if other == piece {
                continue;
            }
            let depth = penetration_depth(world, polygon);
            if depth > overlap {
                overlap = depth;
                blocker = Some(other);
            }
        }
        PlacementCheck {
            outside: outside_depth(world, &self.target),
            overlap,
            blocker,
        }
    }

    /// The placements that fill `corner` and fit: for each unplaced piece and
    /// each of its vertices no wider than the corner, that vertex at the corner
    /// with the edge leaving it along the corner's first side.
    ///
    /// Two kinds of repetition are left out. Of several congruent unplaced
    /// pieces only the lowest-numbered is proposed, and of the vertices that a
    /// piece's own symmetry maps onto each other only the first. Either way the
    /// omitted placement would put the same shape, with the same roof, in the
    /// same place.
    ///
    /// Pieces with roofs must also meet their neighbours' roofs. The slopes
    /// along the contact are compared before any pose exists, through the
    /// compatibility graph; then the heights at the corner; and, once the
    /// placement is known to fit, the heights along every edge it shares with a
    /// placed piece.
    ///
    /// If the pieces are assumed to meet edge to edge ([`Meeting`]), a
    /// placement that meets a placed piece in a T is left out, and so, by the
    /// rules that follow from the assumption, are placements that no assembly
    /// of that kind contains.
    ///
    /// For a convex corner the list is complete in the sense of the module
    /// documentation. For any other corner it is a list of legal placements and
    /// nothing more.
    pub fn propose(&mut self, corner: &Corner) -> Vec<CandidatePlacement> {
        let mut candidates = Vec::new();
        let mut classes_seen = Vec::new();
        for piece in 0..self.shapes.len() {
            if self.poses[piece].is_some() {
                continue;
            }
            let class = self.graph.class(piece);
            if classes_seen.contains(&class) {
                continue;
            }
            classes_seen.push(class);
            let vertices = self.shapes[piece].polygon.len() / self.graph.symmetry(piece);
            for vertex in 0..vertices {
                let angle = self.graph.signatures(piece)[vertex].angle_start;
                if angle > corner.angle + self.tolerance.angle
                    || !self.graph.compatible(corner.source, piece, vertex)
                {
                    continue;
                }
                let pose = pose_at_corner(
                    &self.shapes[piece].polygon,
                    vertex,
                    corner.vertex,
                    corner.direction,
                );
                self.stats.generated += 1;
                if !self.roofs_meet_at(corner, piece, vertex) {
                    self.stats.rejected_roof += 1;
                    continue;
                }
                let world = transform(&self.shapes[piece].polygon, &pose);
                if outside_depth(&world, &self.target) > self.tolerance.length {
                    self.stats.rejected_outside += 1;
                } else if self.enters_a_placed_piece(&world) {
                    self.stats.rejected_overlap += 1;
                } else if self.meeting.edge_to_edge && self.makes_a_junction(&world) {
                    self.stats.rejected_junction += 1;
                } else if self.meeting.uses_wall_edges() && self.strands_an_edge(piece, &world) {
                    self.stats.rejected_wall += 1;
                } else if self.roof_step_of(piece, &pose, &world) > self.tolerance.height {
                    self.stats.rejected_roof += 1;
                } else {
                    candidates.push(CandidatePlacement {
                        piece,
                        pose,
                        vertex,
                        contact: corner.source,
                    });
                }
            }
        }
        candidates
    }

    /// Whether the roof of `piece` at its vertex `vertex` is as high as the
    /// roof of the piece the corner's first side belongs to, at the corner.
    /// True when either has no roof, and for a side that belongs to the tray.
    fn roofs_meet_at(&self, corner: &Corner, piece: usize, vertex: usize) -> bool {
        let EdgeRef::Piece { piece: fixed, .. } = corner.source else {
            return true;
        };
        let (Some(height), Some(roof), Some(pose)) = (
            self.graph.signatures(piece)[vertex].height_start,
            &self.shapes[fixed].roof,
            &self.poses[fixed],
        ) else {
            return true;
        };
        (roof_height(roof, pose, corner.vertex) - height).abs() <= self.tolerance.height
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::graph::Meeting;
    use crate::polygon::{centroid, signed_area};
    use crate::testing::{TOL, Tiling, close, tiling};
    use proptest::prelude::*;
    use std::f64::consts::FRAC_PI_2;
    use tiling_core::Roof;

    fn bare(polygon: Vec<Vec2>) -> Shape {
        Shape {
            polygon,
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

    fn tray() -> Vec<Vec2> {
        vec![[0.0, 0.0], [4.0, 0.0], [4.0, 4.0], [0.0, 4.0]]
    }

    fn at(x: f64, y: f64, theta: f64) -> Pose {
        Pose { x, y, theta }
    }

    /// Depth-first search over one convex corner per node: the rule the module
    /// documentation argues for. Returns every assembly as world polygons.
    fn solve_all(assembly: &mut Assembly, found: &mut Vec<Vec<Vec<Vec2>>>) {
        let corners = assembly.frontier();
        if assembly.all_placed() {
            if corners.is_empty() {
                found.push(
                    (0..assembly.piece_count())
                        .map(|p| assembly.world[p].clone().unwrap())
                        .collect(),
                );
            }
            return;
        }
        let tolerance = *assembly.tolerance();
        let mut best: Option<Vec<CandidatePlacement>> = None;
        for corner in corners.iter().filter(|c| c.is_convex(&tolerance)) {
            let candidates = assembly.propose(corner);
            if best.as_ref().is_none_or(|b| candidates.len() < b.len()) {
                best = Some(candidates);
            }
        }
        for candidate in best.unwrap_or_default() {
            assembly.place(candidate.piece, candidate.pose).unwrap();
            solve_all(assembly, found);
            assembly.undo();
        }
    }

    fn same_polygon(a: &[Vec2], b: &[Vec2], tolerance: f64) -> bool {
        let n = a.len();
        n == b.len()
            && (0..n).any(|s| {
                (0..n).all(|i| {
                    let (p, q) = (a[i], b[(i + s) % n]);
                    (p[0] - q[0]).hypot(p[1] - q[1]) <= tolerance
                })
            })
    }

    /// Whether two assemblies are the same set of polygons, whichever piece is which.
    fn same_assembly(a: &[Vec<Vec2>], b: &[Vec<Vec2>]) -> bool {
        a.len() == b.len() && a.iter().all(|p| b.iter().any(|q| same_polygon(p, q, 1e-6)))
    }

    #[test]
    fn construction_refuses_bad_input() {
        let ok = || vec![bare(rectangle(2.0, 1.0))];
        let mut clockwise = rectangle(2.0, 1.0);
        clockwise.reverse();
        assert_eq!(
            Assembly::new(clockwise.clone(), ok(), TOL).unwrap_err(),
            AssemblyError::NotConvex(None)
        );
        assert_eq!(
            Assembly::new(tray(), vec![ok().remove(0), bare(clockwise)], TOL).unwrap_err(),
            AssemblyError::NotConvex(Some(1))
        );
        let zero = ContactTolerance { length: 0.0, ..TOL };
        assert_eq!(
            Assembly::new(tray(), ok(), zero).unwrap_err(),
            AssemblyError::BadTolerance
        );
    }

    #[test]
    fn placing_and_undoing_is_a_stack() {
        let shapes = vec![bare(rectangle(2.0, 1.0)), bare(rectangle(2.0, 1.0))];
        let mut assembly = Assembly::new(tray(), shapes, TOL).unwrap();
        assert_eq!(assembly.undo(), None);
        assembly.place(1, at(1.0, 0.5, 0.0)).unwrap();
        assert_eq!(
            assembly.place(1, at(3.0, 0.5, 0.0)),
            Err(AssemblyError::AlreadyPlaced(1))
        );
        assert_eq!(
            assembly.place(2, at(3.0, 0.5, 0.0)),
            Err(AssemblyError::NoSuchPiece(2))
        );
        assembly.place(0, at(3.0, 0.5, 0.0)).unwrap();
        assert_eq!(assembly.placed(), &[1, 0]);
        assert_eq!(assembly.pose(0), Some(at(3.0, 0.5, 0.0)));
        assert!(assembly.all_placed());
        assert_eq!(assembly.undo(), Some(0));
        assert_eq!(assembly.pose(0), None);
        assert_eq!(assembly.placed(), &[1]);
        // The frontier is that of the one block left: see contact.rs for the L shape.
        assert_eq!(assembly.frontier().len(), 6);
    }

    #[test]
    fn check_placement_measures_outside_and_overlap() {
        let shapes = vec![bare(rectangle(2.0, 1.0)), bare(rectangle(2.0, 1.0))];
        let mut assembly = Assembly::new(tray(), shapes, TOL).unwrap();
        assembly.place(0, at(1.0, 0.5, 0.0)).unwrap();
        // Beside the first block: fits.
        let beside = assembly.check_placement(1, &at(3.0, 0.5, 0.0)).unwrap();
        assert_eq!(
            beside,
            PlacementCheck {
                outside: 0.0,
                overlap: 0.0,
                blocker: None
            }
        );
        assert!(beside.fits(&TOL));
        // Shifted 0.25 left: 0.25 into the first block.
        let into = assembly.check_placement(1, &at(2.75, 0.5, 0.0)).unwrap();
        assert!(close(into.overlap, 0.25, 1e-12) && into.blocker == Some(0));
        assert!(!into.fits(&TOL));
        // Shifted 0.5 right and 0.3 down: beyond the corner by hypot(0.5, 0.3).
        let out = assembly.check_placement(1, &at(3.5, 0.2, 0.0)).unwrap();
        assert!(close(out.outside, 0.5f64.hypot(0.3), 1e-12) && out.overlap == 0.0);
        // A placed piece is not measured against itself.
        let itself = assembly.check_placement(0, &at(1.0, 0.5, 0.0)).unwrap();
        assert_eq!(itself.overlap, 0.0);
        assert!(assembly.check_placement(5, &at(0.0, 0.0, 0.0)).is_err());
    }

    #[test]
    fn proposals_for_a_tray_corner() {
        // A 2 by 1 block and a 3-4-5 triangle, into the bottom-left corner of a 4 by 4 tray.
        let triangle = {
            let raw = [[0.0, 0.0], [4.0, 0.0], [0.0, 3.0]];
            let [cx, cy] = centroid(&raw);
            raw.iter()
                .map(|p| [p[0] - cx, p[1] - cy])
                .collect::<Vec<_>>()
        };
        let shapes = vec![bare(rectangle(2.0, 1.0)), bare(triangle)];
        let mut assembly = Assembly::new(tray(), shapes, TOL).unwrap();
        let corner = assembly.frontier()[0];
        assert_eq!(corner.vertex, [0.0, 0.0]);
        let candidates = assembly.propose(&corner);
        // The block: its symmetry leaves vertices 0 and 1, lying or standing.
        // The triangle: each of its three corners is at most a right angle and all fit
        // (with the hypotenuse along the bottom it is 5 long; that reaches outside).
        let summary: Vec<(usize, usize)> = candidates.iter().map(|c| (c.piece, c.vertex)).collect();
        assert_eq!(summary, vec![(0, 0), (0, 1), (1, 0), (1, 2)]);
        assert!(
            candidates
                .iter()
                .all(|c| c.contact == EdgeRef::Tray { edge: 0 })
        );
        // Lying: centre (1, 0.5), unturned. Standing: centre (0.5, 1), a quarter turn back.
        assert!(
            close(candidates[0].pose.x, 1.0, 1e-12) && close(candidates[0].pose.theta, 0.0, 1e-12)
        );
        assert!(close(candidates[1].pose.x, 0.5, 1e-12) && close(candidates[1].pose.y, 1.0, 1e-12));
        assert!(close(candidates[1].pose.theta, -FRAC_PI_2, 1e-12));
        assert_eq!(
            assembly.stats(),
            CandidateStats {
                generated: 5,
                rejected_outside: 1,
                rejected_overlap: 0,
                rejected_roof: 0,
                rejected_junction: 0,
                rejected_wall: 0,
            }
        );
    }

    #[test]
    fn proposals_skip_twins_and_wide_angles_and_blocked_places() {
        // Two identical blocks and a square too big for what is left.
        let shapes = vec![
            bare(rectangle(2.0, 1.0)),
            bare(rectangle(2.0, 1.0)),
            bare(rectangle(3.5, 3.5)),
        ];
        let mut assembly = Assembly::new(tray(), shapes, TOL).unwrap();
        assembly.place(2, at(1.75, 1.75, 0.0)).unwrap();
        // The corner at (3.5, 0) on the bottom wall, beside the big square.
        let corner = *assembly
            .frontier()
            .iter()
            .find(|c| close(c.vertex[0], 3.5, 1e-9) && close(c.vertex[1], 0.0, 1e-9))
            .unwrap();
        // A block fits there in neither orientation: the gap is 0.5 wide.
        assert!(assembly.propose(&corner).is_empty());
        // Both orientations of the first block were tried and the second block was not.
        assert_eq!(assembly.stats().generated, 2);
        assert_eq!(assembly.stats().rejected_outside, 2);
    }

    /// A 2 x 4 strip under a level roof at height 1 against the left wall, a
    /// 2 x 2 square at the same height, and a 3 x 2 block one higher.
    fn roofed() -> Assembly {
        let level = |polygon, z0| Shape {
            polygon,
            roof: Some(Roof {
                z0,
                gx: 0.0,
                gy: 0.0,
            }),
        };
        let shapes = vec![
            level(rectangle(2.0, 4.0), 1.0),
            level(rectangle(2.0, 2.0), 1.0),
            level(rectangle(3.0, 2.0), 2.0),
        ];
        let mut assembly = Assembly::new(tray(), shapes, TOL).unwrap();
        assembly.place(0, at(1.0, 2.0, 0.0)).unwrap();
        assembly
    }

    fn corner_at(assembly: &Assembly, x: f64, y: f64) -> Corner {
        *assembly
            .frontier()
            .iter()
            .find(|c| close(c.vertex[0], x, 1e-9) && close(c.vertex[1], y, 1e-9))
            .unwrap()
    }

    #[test]
    fn a_roof_step_along_a_seam_refuses_a_placement_that_fits() {
        // The corner at (2, 0) starts along the tray's wall, which has no roof:
        // nothing can be told at the corner. The block fits standing up, over
        // x in [2, 4] and y in [0, 3], and there it lies against the strip one
        // millimetre higher. Lying down it reaches x = 5, outside the tray.
        let mut assembly = roofed();
        let corner = corner_at(&assembly, 2.0, 0.0);
        assert!(matches!(corner.source, EdgeRef::Tray { .. }));
        let proposals = assembly.propose(&corner);
        assert_eq!(proposals.iter().map(|c| c.piece).collect::<Vec<_>>(), [1]);
        let stats = assembly.stats();
        assert_eq!(
            (stats.generated, stats.rejected_outside, stats.rejected_roof),
            (3, 1, 1)
        );
        assert!(close(
            assembly.roof_step(2, &at(3.0, 1.5, FRAC_PI_2)).unwrap(),
            1.0,
            1e-12
        ));
    }

    #[test]
    fn a_roof_at_the_wrong_height_is_refused_at_the_corner_before_it_is_placed() {
        // The corner at (2, 4) starts down the strip's own edge, so the strip's
        // roof is known there. Both ways round the block is a millimetre too
        // high at the corner, and it is refused for that, also the way round
        // that would stick out of the tray: the roof is asked first.
        let mut assembly = roofed();
        let corner = corner_at(&assembly, 2.0, 4.0);
        assert!(matches!(corner.source, EdgeRef::Piece { piece: 0, .. }));
        let proposals = assembly.propose(&corner);
        assert_eq!(proposals.iter().map(|c| c.piece).collect::<Vec<_>>(), [1]);
        let stats = assembly.stats();
        assert_eq!(
            (stats.generated, stats.rejected_outside, stats.rejected_roof),
            (3, 0, 2)
        );
    }

    #[test]
    fn four_identical_squares_have_one_assembly() {
        let shapes = (0..4).map(|_| bare(rectangle(2.0, 2.0))).collect();
        let mut assembly = Assembly::new(tray(), shapes, TOL).unwrap();
        let mut found = Vec::new();
        solve_all(&mut assembly, &mut found);
        assert_eq!(found.len(), 1);
        assert!(
            assembly.placed().is_empty(),
            "the search leaves the state as it found it"
        );
    }

    #[test]
    fn two_unequal_strips_have_four_assemblies() {
        // The narrow strip against each wall in turn.
        let shapes = vec![bare(rectangle(1.0, 4.0)), bare(rectangle(3.0, 4.0))];
        let mut assembly = Assembly::new(tray(), shapes, TOL).unwrap();
        let mut found = Vec::new();
        solve_all(&mut assembly, &mut found);
        assert_eq!(found.len(), 4);
        for (i, a) in found.iter().enumerate() {
            for b in &found[i + 1..] {
                assert!(!same_assembly(a, b));
            }
        }
    }

    #[test]
    fn pieces_that_cannot_fill_the_tray_have_no_assembly() {
        let shapes = vec![bare(rectangle(1.0, 4.0)), bare(rectangle(2.0, 4.0))];
        let mut assembly = Assembly::new(tray(), shapes, TOL).unwrap();
        let mut found = Vec::new();
        solve_all(&mut assembly, &mut found);
        assert!(found.is_empty());
    }

    /// An assembly over a generated tiling, pieces in local coordinates.
    fn assembly_of(tiling: &Tiling) -> Assembly {
        let shapes = tiling.local.iter().cloned().map(bare).collect();
        Assembly::new(tiling.target.clone(), shapes, TOL).unwrap()
    }

    proptest! {
        #[test]
        fn a_generated_tiling_is_exact(tiling in tiling()) {
            let total: f64 = tiling.world.iter().map(|p| signed_area(p)).sum();
            prop_assert!(close(total, signed_area(&tiling.target), 1e-6));
            for (local, (pose, world)) in tiling.local.iter().zip(tiling.poses.iter().zip(&tiling.world)) {
                prop_assert!(same_polygon(&transform(local, pose), world, 1e-9));
            }
        }

        #[test]
        fn the_true_placements_fit_and_cover(tiling in tiling()) {
            let mut assembly = assembly_of(&tiling);
            for (piece, pose) in tiling.poses.iter().enumerate() {
                prop_assert!(assembly.check_placement(piece, pose).unwrap().fits(&TOL));
                assembly.place(piece, *pose).unwrap();
            }
            prop_assert!(assembly.frontier().is_empty());
        }

        /// The heart of the search: whatever part of a tiling is already down,
        /// every convex corner of the rest is filled by one of its proposals,
        /// exactly as some remaining piece fills it in the tiling.
        #[test]
        fn every_convex_corner_is_offered_its_true_filler(tiling in tiling(), mask in any::<u32>()) {
            let mut assembly = assembly_of(&tiling);
            let count = tiling.world.len();
            let placed: Vec<bool> = (0..count).map(|p| mask >> p & 1 == 1).collect();
            prop_assume!(placed.iter().any(|&down| !down));
            for piece in (0..count).filter(|&p| placed[p]) {
                assembly.place(piece, tiling.poses[piece]).unwrap();
            }
            let corners = assembly.frontier();
            let convex: Vec<&Corner> = corners.iter().filter(|c| c.is_convex(&TOL)).collect();
            prop_assert!(!convex.is_empty(), "an uncovered region has a convex corner");
            for corner in convex {
                let candidates = assembly.propose(corner);
                let offered = candidates.iter().any(|candidate| {
                    let world = transform(&tiling.local[candidate.piece], &candidate.pose);
                    (0..count).any(|p| !placed[p] && same_polygon(&world, &tiling.world[p], 1e-6))
                });
                prop_assert!(offered, "no proposal fills the corner at {:?} as the tiling does", corner.vertex);
                for candidate in &candidates {
                    let check = assembly.check_placement(candidate.piece, &candidate.pose).unwrap();
                    prop_assert!(check.fits(&TOL));
                }
            }
        }

        #[test]
        fn the_search_finds_the_tiling_it_was_cut_from(tiling in tiling()) {
            let mut assembly = assembly_of(&tiling);
            let mut found = Vec::new();
            solve_all(&mut assembly, &mut found);
            prop_assert!(found.iter().any(|a| same_assembly(a, &tiling.world)));
            // Every assembly found is a tiling: it covers the target without overlap.
            for a in &found {
                let total: f64 = a.iter().map(|p| signed_area(p)).sum();
                prop_assert!(close(total, signed_area(&tiling.target), 1e-6));
                for (i, p) in a.iter().enumerate() {
                    prop_assert!(outside_depth(p, &tiling.target) <= 1e-6);
                    for q in &a[i + 1..] {
                        prop_assert!(penetration_depth(p, q) <= 1e-6);
                    }
                }
            }
        }
    }

    /// A 4 by 2 block and two 2 by 2 squares fill a 4 by 4 tray in one way, and
    /// in it the squares' shared corner stands in the middle of the block's long
    /// edge: a T.
    fn block_and_squares(meeting: Meeting) -> Assembly {
        let shapes = vec![
            bare(rectangle(4.0, 2.0)),
            bare(rectangle(2.0, 2.0)),
            bare(rectangle(2.0, 2.0)),
        ];
        Assembly::meeting(tray(), shapes, TOL, meeting).unwrap()
    }

    #[test]
    fn a_placement_that_makes_a_t_is_refused_only_under_the_assumption() {
        // The junction check alone: neither rule that follows from the assumption.
        let only = Meeting {
            edge_to_edge: true,
            equal_edges: false,
            wall_edges: false,
        };
        for (meeting, offered) in [(Meeting::default(), true), (only, false)] {
            let mut assembly = block_and_squares(meeting);
            assembly.place(0, at(2.0, 1.0, 0.0)).unwrap();
            // The corner over the block's top-left vertex. A square there has its
            // bottom-right vertex at (2, 2), inside the block's top edge.
            let corner = corner_at(&assembly, 0.0, 2.0);
            let candidates = assembly.propose(&corner);
            let square = candidates.iter().any(|c| c.piece == 1);
            assert_eq!(square, offered, "{meeting:?}");
            assert_eq!(
                assembly.stats().rejected_junction > 0,
                !offered,
                "{meeting:?}"
            );
        }
        // Two pieces meeting along a whole edge are no T: one square on another.
        // The block lying over the square is one: the square's top-right vertex,
        // (2, 2), is inside its bottom edge. Standing, it reaches outside.
        let mut assembly = block_and_squares(only);
        assembly.place(1, at(1.0, 1.0, 0.0)).unwrap();
        let corner = corner_at(&assembly, 0.0, 2.0);
        let pieces: Vec<usize> = assembly.propose(&corner).iter().map(|c| c.piece).collect();
        assert_eq!(pieces, vec![2]);
        assert_eq!(assembly.stats().rejected_junction, 1);
    }

    #[test]
    fn an_edge_no_other_piece_matches_is_kept_on_the_tray() {
        let assembly = block_and_squares(Meeting::edge_to_edge());
        // The block's long edges (0 and 2, 4 long) have no partner; its short ones
        // match a square's side, and every side of a square matches the other square.
        let partners: Vec<bool> = (0..4).map(|e| assembly.graph().has_partner(0, e)).collect();
        assert_eq!(partners, vec![false, true, false, true]);
        assert!((0..4).all(|e| assembly.graph().has_partner(1, e)));

        // In the empty tray's corner the block, lying or standing, puts a long edge
        // off the wall; only the square is offered.
        for (wall_edges, block) in [(true, false), (false, true)] {
            let meeting = Meeting {
                wall_edges,
                ..Meeting::edge_to_edge()
            };
            let mut assembly = block_and_squares(meeting);
            let corner = corner_at(&assembly, 0.0, 0.0);
            let candidates = assembly.propose(&corner);
            assert_eq!(candidates.iter().any(|c| c.piece == 0), block);
            assert!(candidates.iter().any(|c| c.piece == 1));
            assert_eq!(
                assembly.stats().rejected_wall,
                if wall_edges { 2 } else { 0 }
            );
        }
    }

    #[test]
    fn without_the_assumption_its_rules_do_nothing() {
        let rules_alone = Meeting {
            edge_to_edge: false,
            equal_edges: true,
            wall_edges: true,
        };
        let mut plain = block_and_squares(Meeting::default());
        let mut alone = block_and_squares(rules_alone);
        assert_eq!(plain.graph().arc_count(), alone.graph().arc_count());
        let corner = corner_at(&plain, 0.0, 0.0);
        assert_eq!(plain.propose(&corner), alone.propose(&corner));
        assert_eq!(plain.stats(), alone.stats());
    }
}
