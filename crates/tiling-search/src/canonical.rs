//! When two assemblies are the same, and one form to stand for all of them.
//!
//! Three things can differ between assemblies that nobody would call different:
//!
//! - which of several congruent pieces sits where;
//! - a piece turned onto itself, a square by a quarter turn;
//! - the whole assembly turned with the tray, a square tray by a quarter turn.
//!
//! [`Symmetry::canonical`] removes all three. A piece is described by its
//! *seat*: where its centroid is and how it is turned, the turn taken modulo
//! the piece's own symmetry. Congruent pieces need not be stored the same way
//! round, so the turn is measured for the first piece of the class: the turn
//! that piece would need to lie exactly where this one does. Within a class of congruent pieces the seats are
//! put in order and dealt out to the pieces by index. That is done for each
//! rotation of the tray, and the rotation whose list of seats comes first is
//! kept.
//!
//! Comparisons are in `f64` with the search's tolerances: two numbers within
//! the tolerance are equal, and otherwise the smaller comes first. Such an
//! order is only as good as the gap between "equal" and "different". In an
//! assembly, seats that differ do so by millimetres and seats that agree do so
//! to rounding, with the tolerance far from both.

use std::cmp::Ordering;
use std::f64::consts::{PI, TAU};

use tiling_core::{Pose, Vec2};
use tiling_geometry::{ContactTolerance, EdgeGraph, Shape, centroid, rotation_order};

/// Where a piece sits: its centroid in the world, and its turn in `[0, period)`.
#[derive(Debug, Clone, Copy, PartialEq)]
struct Seat {
    x: f64,
    y: f64,
    turn: f64,
}

/// One way of putting down a piece of a class, whichever member of the class
/// it is and whichever of the turns onto itself it has: the seat, with the
/// class it is a seat for.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Placement {
    /// The class: its lowest-numbered piece.
    pub class: usize,
    /// The centroid of the placed piece, in the world.
    pub x: f64,
    pub y: f64,
    /// The turn of the class's first piece that puts it there, in `[0, period)`.
    pub turn: f64,
}

/// The symmetries of one puzzle: of its tray, and of and among its pieces.
#[derive(Debug, Clone)]
pub struct Symmetry {
    centre: Vec2,
    tray_order: usize,
    classes: Vec<usize>,
    /// For each piece, the smallest turn that maps it onto itself.
    periods: Vec<f64>,
    /// For each piece, the turn that takes the first piece of its class onto it.
    /// A seat's turn is that of the class's first piece, were it sitting there.
    offsets: Vec<f64>,
    /// Local centroids. A turn about this point is what maps a piece onto itself.
    centroids: Vec<Vec2>,
    length: f64,
    angle: f64,
}

impl Symmetry {
    pub fn new(
        target: &[Vec2],
        shapes: &[Shape],
        graph: &EdgeGraph,
        tolerance: &ContactTolerance,
    ) -> Symmetry {
        Symmetry {
            centre: centroid(target),
            tray_order: rotation_order(target, tolerance),
            classes: (0..shapes.len()).map(|p| graph.class(p)).collect(),
            periods: (0..shapes.len())
                .map(|p| TAU / graph.symmetry(p) as f64)
                .collect(),
            offsets: (0..shapes.len())
                .map(|p| graph.turn_from_class(p))
                .collect(),
            centroids: shapes.iter().map(|s| centroid(&s.polygon)).collect(),
            length: tolerance.length,
            angle: tolerance.angle,
        }
    }

    /// How many rotations map the tray onto itself.
    pub fn tray_order(&self) -> usize {
        self.tray_order
    }

    /// The point the tray turns about.
    pub fn centre(&self) -> Vec2 {
        self.centre
    }

    /// The class of each piece: the lowest-numbered piece congruent to it.
    pub fn classes(&self) -> &[usize] {
        &self.classes
    }

    /// The placement that `piece` at `pose` is.
    pub fn placement(&self, piece: usize, pose: &Pose) -> Placement {
        let seat = self.seat(piece, pose);
        Placement {
            class: self.classes[piece],
            x: seat.x,
            y: seat.y,
            turn: seat.turn,
        }
    }

    /// A pose that puts `piece`, a member of the placement's class, there.
    pub fn pose_for(&self, piece: usize, placement: &Placement) -> Pose {
        debug_assert_eq!(self.classes[piece], placement.class);
        self.pose(
            piece,
            &Seat {
                x: placement.x,
                y: placement.y,
                turn: placement.turn,
            },
        )
    }

    /// Whether two placements put the same polygon in the same place.
    pub fn same_placement(&self, a: &Placement, b: &Placement) -> bool {
        let seat = |p: &Placement| Seat {
            x: p.x,
            y: p.y,
            turn: p.turn,
        };
        a.class == b.class && self.compare(&seat(a), &seat(b)).is_eq()
    }

    /// A turn brought into `[0, period)`, with anything within the tolerance of
    /// a whole period counted as none.
    fn reduced(&self, turn: f64, period: f64) -> f64 {
        let turn = turn.rem_euclid(period);
        if period - turn <= self.angle {
            0.0
        } else {
            turn
        }
    }

    fn seat(&self, piece: usize, pose: &Pose) -> Seat {
        let [x, y] = pose.apply(self.centroids[piece]);
        Seat {
            x,
            y,
            turn: self.reduced(pose.theta + self.offsets[piece], self.periods[piece]),
        }
    }

    fn pose(&self, piece: usize, seat: &Seat) -> Pose {
        // The same range as `pose_at_corner` uses.
        let theta = PI - (PI - (seat.turn - self.offsets[piece])).rem_euclid(TAU);
        let (s, c) = theta.sin_cos();
        let [lx, ly] = self.centroids[piece];
        Pose {
            x: seat.x - (c * lx - s * ly),
            y: seat.y - (s * lx + c * ly),
            theta,
        }
    }

    fn compare(&self, a: &Seat, b: &Seat) -> Ordering {
        if (a.x - b.x).abs() > self.length {
            a.x.total_cmp(&b.x)
        } else if (a.y - b.y).abs() > self.length {
            a.y.total_cmp(&b.y)
        } else if (a.turn - b.turn).abs() > self.angle {
            a.turn.total_cmp(&b.turn)
        } else {
            Ordering::Equal
        }
    }

    fn compare_all(&self, a: &[Seat], b: &[Seat]) -> Ordering {
        a.iter()
            .zip(b)
            .map(|(x, y)| self.compare(x, y))
            .find(|order| order.is_ne())
            .unwrap_or(Ordering::Equal)
    }

    /// The seats of an assembly turned with the tray by `step` of its
    /// rotations, congruent pieces put in order.
    fn seats(&self, poses: &[Pose], step: usize) -> Vec<Seat> {
        let turn = step as f64 * TAU / self.tray_order as f64;
        let (s, c) = turn.sin_cos();
        let mut seats: Vec<Seat> = poses
            .iter()
            .enumerate()
            .map(|(piece, pose)| {
                let seat = self.seat(piece, pose);
                let (dx, dy) = (seat.x - self.centre[0], seat.y - self.centre[1]);
                Seat {
                    x: self.centre[0] + c * dx - s * dy,
                    y: self.centre[1] + s * dx + c * dy,
                    turn: self.reduced(seat.turn + turn, self.periods[piece]),
                }
            })
            .collect();
        for class in 0..poses.len() {
            let members: Vec<usize> = (class..poses.len())
                .filter(|&p| self.classes[p] == class)
                .collect();
            // An insertion sort: the tolerant order is not one a library sort may rely on.
            for i in 1..members.len() {
                let mut j = i;
                while j > 0
                    && self
                        .compare(&seats[members[j]], &seats[members[j - 1]])
                        .is_lt()
                {
                    seats.swap(members[j], members[j - 1]);
                    j -= 1;
                }
            }
        }
        seats
    }

    fn canonical_seats(&self, poses: &[Pose]) -> Vec<Seat> {
        let mut best = self.seats(poses, 0);
        for step in 1..self.tray_order {
            let seats = self.seats(poses, step);
            if self.compare_all(&seats, &best).is_lt() {
                best = seats;
            }
        }
        best
    }

    /// The canonical form of an assembly: one pose per piece, the same for
    /// every assembly that differs from this one only by exchanging congruent
    /// pieces, turning pieces onto themselves, or turning the tray.
    pub fn canonical(&self, poses: &[Pose]) -> Vec<Pose> {
        self.canonical_seats(poses)
            .iter()
            .enumerate()
            .map(|(piece, seat)| self.pose(piece, seat))
            .collect()
    }

    /// Whether two assemblies have the same canonical form.
    pub fn same(&self, a: &[Pose], b: &[Pose]) -> bool {
        a.len() == b.len()
            && self
                .compare_all(&self.canonical_seats(a), &self.canonical_seats(b))
                .is_eq()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::f64::consts::FRAC_PI_2;
    use tiling_geometry::transform;

    const TOL: ContactTolerance = ContactTolerance {
        length: 1e-7,
        angle: 1e-7,
        slope: 1e-7,
        height: 1e-7,
    };

    fn rectangle(w: f64, h: f64) -> Vec<Vec2> {
        vec![
            [-w / 2.0, -h / 2.0],
            [w / 2.0, -h / 2.0],
            [w / 2.0, h / 2.0],
            [-w / 2.0, h / 2.0],
        ]
    }

    fn symmetry_of(target: &[Vec2], polygons: &[Vec<Vec2>]) -> Symmetry {
        let shapes: Vec<Shape> = polygons
            .iter()
            .map(|polygon| Shape {
                polygon: polygon.clone(),
                roof: None,
            })
            .collect();
        Symmetry::new(target, &shapes, &EdgeGraph::build(&shapes, &TOL), &TOL)
    }

    fn at(x: f64, y: f64, theta: f64) -> Pose {
        Pose { x, y, theta }
    }

    /// A square tray of side 4 about (2, 2); a 1 x 4 strip, a 3 x 4 block.
    fn strips() -> (Vec<Vec2>, Vec<Vec<Vec2>>) {
        (
            vec![[0.0, 0.0], [4.0, 0.0], [4.0, 4.0], [0.0, 4.0]],
            vec![rectangle(1.0, 4.0), rectangle(3.0, 4.0)],
        )
    }

    #[test]
    fn the_four_turns_of_an_assembly_have_one_form() {
        let (tray, pieces) = strips();
        let symmetry = symmetry_of(&tray, &pieces);
        assert_eq!(symmetry.tray_order(), 4);
        // The strip against the left wall, then the same turned with the tray by
        // quarter turns: against the bottom, the right and the top.
        let turns = [
            [at(0.5, 2.0, 0.0), at(2.5, 2.0, 0.0)],
            [at(2.0, 0.5, FRAC_PI_2), at(2.0, 2.5, FRAC_PI_2)],
            [at(3.5, 2.0, 0.0), at(1.5, 2.0, 0.0)],
            [at(2.0, 3.5, FRAC_PI_2), at(2.0, 1.5, FRAC_PI_2)],
        ];
        let form = symmetry.canonical(&turns[0]);
        for other in &turns {
            assert!(symmetry.same(&turns[0], other));
            let again = symmetry.canonical(other);
            for (p, q) in form.iter().zip(&again) {
                assert!((p.x - q.x).abs() <= 1e-9 && (p.y - q.y).abs() <= 1e-9);
                assert!((p.theta - q.theta).abs() <= 1e-9);
            }
        }
        // The form is one of the four: its pieces still tile the tray.
        let strip = transform(&pieces[0], &form[0]);
        assert!(
            strip
                .iter()
                .all(|p| (-1e-9..=4.0 + 1e-9).contains(&p[0])
                    && (-1e-9..=4.0 + 1e-9).contains(&p[1]))
        );
    }

    #[test]
    fn a_half_turn_of_a_rectangle_is_no_turn() {
        let (tray, pieces) = strips();
        let symmetry = symmetry_of(&tray, &pieces);
        let plain = [at(0.5, 2.0, 0.0), at(2.5, 2.0, 0.0)];
        let flipped = [at(0.5, 2.0, PI), at(2.5, 2.0, -PI)];
        assert!(symmetry.same(&plain, &flipped));
    }

    #[test]
    fn a_different_assembly_has_a_different_form() {
        // A tray that is not square, so that nothing can be turned into anything else.
        let tray = vec![[0.0, 0.0], [4.0, 0.0], [4.0, 3.0], [0.0, 3.0]];
        let pieces = vec![rectangle(1.0, 3.0), rectangle(3.0, 3.0)];
        let symmetry = symmetry_of(&tray, &pieces);
        assert_eq!(symmetry.tray_order(), 2);
        let left = [at(0.5, 1.5, 0.0), at(2.5, 1.5, 0.0)];
        let right = [at(3.5, 1.5, 0.0), at(1.5, 1.5, 0.0)];
        // Left and right are each other's half turn about (2, 1.5).
        assert!(symmetry.same(&left, &right));
        let shifted = [at(0.5, 1.5, 0.0), at(2.6, 1.5, 0.0)];
        assert!(!symmetry.same(&left, &shifted));
        // So is a piece moved only up, and a piece only turned (by other than its half turn).
        let raised = [at(0.5, 1.6, 0.0), at(2.5, 1.5, 0.0)];
        assert!(!symmetry.same(&left, &raised));
        let turned = [at(0.5, 1.5, 0.3), at(2.5, 1.5, 0.0)];
        assert!(!symmetry.same(&left, &turned));
    }

    #[test]
    fn congruent_pieces_may_change_places() {
        let tray = vec![[0.0, 0.0], [4.0, 0.0], [4.0, 3.0], [0.0, 3.0]];
        let pieces = vec![
            rectangle(1.0, 3.0),
            rectangle(1.0, 3.0),
            rectangle(2.0, 3.0),
        ];
        let symmetry = symmetry_of(&tray, &pieces);
        assert_eq!(symmetry.classes(), &[0, 0, 2]);
        let one = [at(0.5, 1.5, 0.0), at(1.5, 1.5, 0.0), at(3.0, 1.5, 0.0)];
        let swapped = [at(1.5, 1.5, 0.0), at(0.5, 1.5, 0.0), at(3.0, 1.5, 0.0)];
        assert!(symmetry.same(&one, &swapped));
        // The wide piece between the two narrow ones is another assembly.
        let between = [at(0.5, 1.5, 0.0), at(3.5, 1.5, 0.0), at(2.0, 1.5, 0.0)];
        assert!(!symmetry.same(&one, &between));
        // In the form, the lower-numbered twin has the seat that comes first.
        let form = symmetry.canonical(&swapped);
        assert!(form[0].x < form[1].x);
    }

    #[test]
    fn twins_stored_at_different_turns_change_places_with_their_turns() {
        // The second narrow strip is stored lying down: the same piece, a quarter
        // turn round. Standing in the tray it has the pose of a quarter turn.
        let tray = vec![[0.0, 0.0], [4.0, 0.0], [4.0, 3.0], [0.0, 3.0]];
        let pieces = vec![
            rectangle(1.0, 3.0),
            rectangle(3.0, 1.0),
            rectangle(2.0, 3.0),
        ];
        let symmetry = symmetry_of(&tray, &pieces);
        assert_eq!(symmetry.classes(), &[0, 0, 2]);
        let one = [
            at(0.5, 1.5, 0.0),
            at(1.5, 1.5, FRAC_PI_2),
            at(3.0, 1.5, 0.0),
        ];
        let swapped = [
            at(1.5, 1.5, 0.0),
            at(0.5, 1.5, FRAC_PI_2),
            at(3.0, 1.5, 0.0),
        ];
        assert!(symmetry.same(&one, &swapped));
        // The form is still the assembly: by hand, the strips cover x in [0, 1]
        // and [1, 2] and the block [2, 4], each over the tray's whole height.
        for poses in [&one, &swapped] {
            let form = symmetry.canonical(poses);
            let mut spans: Vec<[f64; 4]> = pieces
                .iter()
                .zip(&form)
                .map(|(polygon, pose)| {
                    let world = transform(polygon, pose);
                    let low = |axis: usize| world.iter().map(|p| p[axis]).fold(f64::MAX, f64::min);
                    let high = |axis: usize| world.iter().map(|p| p[axis]).fold(f64::MIN, f64::max);
                    [low(0), high(0), low(1), high(1)]
                })
                .collect();
            spans.sort_by(|a, b| a[0].total_cmp(&b[0]));
            let expected = [
                [0.0, 1.0, 0.0, 3.0],
                [1.0, 2.0, 0.0, 3.0],
                [2.0, 4.0, 0.0, 3.0],
            ];
            for (span, want) in spans.iter().zip(&expected) {
                for (a, b) in span.iter().zip(want) {
                    assert!((a - b).abs() <= 1e-9, "{spans:?}");
                }
            }
        }
    }

    #[test]
    fn a_placement_is_the_same_for_twins_and_for_turns_onto_itself() {
        // Two narrow strips, the second stored lying down, and a block.
        let tray = vec![[0.0, 0.0], [4.0, 0.0], [4.0, 3.0], [0.0, 3.0]];
        let pieces = vec![
            rectangle(1.0, 3.0),
            rectangle(3.0, 1.0),
            rectangle(2.0, 3.0),
        ];
        let symmetry = symmetry_of(&tray, &pieces);
        // Either strip standing against the left wall, either way up.
        let first = symmetry.placement(0, &at(0.5, 1.5, 0.0));
        assert_eq!(first.class, 0);
        for (piece, theta) in [(0, PI), (1, FRAC_PI_2), (1, -FRAC_PI_2)] {
            let other = symmetry.placement(piece, &at(0.5, 1.5, theta));
            assert!(symmetry.same_placement(&first, &other), "{piece} {theta}");
        }
        // Not the strip one column along, nor the strip lying down, nor the block.
        assert!(!symmetry.same_placement(&first, &symmetry.placement(0, &at(1.5, 1.5, 0.0))));
        assert!(!symmetry.same_placement(&first, &symmetry.placement(0, &at(0.5, 1.5, 1.0))));
        assert!(!symmetry.same_placement(&first, &symmetry.placement(2, &at(0.5, 1.5, 0.0))));
        // A pose made for either member puts it over x in [0, 1], y in [0, 3].
        for piece in [0, 1] {
            let world = transform(&pieces[piece], &symmetry.pose_for(piece, &first));
            for corner in [[0.0, 0.0], [1.0, 0.0], [1.0, 3.0], [0.0, 3.0]] {
                assert!(
                    world
                        .iter()
                        .any(|p| (p[0] - corner[0]).hypot(p[1] - corner[1]) <= 1e-9),
                    "{piece}: {world:?}"
                );
            }
        }
    }

    #[test]
    fn a_piece_not_stored_about_its_centroid_is_still_recognised() {
        // The strip stored with a corner at its origin: a half turn about the origin
        // moves it, a half turn about its centroid does not.
        let tray = vec![[0.0, 0.0], [4.0, 0.0], [4.0, 3.0], [0.0, 3.0]];
        let strip = vec![[0.0, 0.0], [1.0, 0.0], [1.0, 3.0], [0.0, 3.0]];
        let symmetry = symmetry_of(&tray, &[strip.clone(), rectangle(3.0, 3.0)]);
        let plain = [at(0.0, 0.0, 0.0), at(2.5, 1.5, 0.0)];
        let flipped = [at(1.0, 3.0, PI), at(2.5, 1.5, 0.0)];
        assert!(symmetry.same(&plain, &flipped));
        let form = symmetry.canonical(&flipped);
        let world = transform(&strip, &form[0]);
        let cx: f64 = world.iter().map(|p| p[0]).sum::<f64>() / 4.0;
        assert!((cx - 0.5).abs() <= 1e-9 || (cx - 3.5).abs() <= 1e-9);
    }
}
