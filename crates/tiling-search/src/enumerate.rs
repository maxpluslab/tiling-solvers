//! A finite set of placements, and which of them exclude one another.
//!
//! Some solvers do not generate placements as they go: they are handed a list
//! and choose from it. CP-SAT is one. This module builds the list.
//!
//! **The placements** are the ones the corner search of [`contact_dfs`] puts
//! down anywhere in its tree: the *reachable* placements. Every assembly that
//! search can find is made of them, since the search placed each of its pieces
//! on the way there. So choosing among the reachable placements loses no
//! assembly the search has.
//!
//! The set is small. The search visits the same placement in many states: on
//! the corpus a tree of a million nodes holds a few thousand distinct
//! placements. A set built without a search, by closing the contacts of
//! placements under further contacts, was tried and is not small: it forgets
//! which pieces a chain of contacts has already used, and on a six-piece
//! puzzle it passed three thousand placements while still growing.
//!
//! The price is that building the set costs one whole search. What a chooser
//! then adds is a second opinion on which of them fit together, reached by
//! other means.
//!
//! **The conflicts** come from [`tiling_geometry::conflicts`]: overlap, and
//! for pieces with roofs a step between neighbouring roofs.
//!
//! **Why choosing is enough.** Take one placement for every piece (for a class
//! of congruent pieces, as many placements as it has members), no two in
//! conflict. Every reachable placement lies inside the target. The areas of
//! the pieces add up to the target's. Pieces inside the target that do not
//! overlap and have its area cover it ([`Model::areas_add_up`] says whether
//! they have; if not, no choice is an assembly). So such a choice is an assembly, and
//! in the relief regime one whose roofs are continuous along every shared
//! edge stretch. This is an argument about exact figures; the code is `f64`
//! with tolerances.

use std::collections::HashMap;
use std::f64::consts::TAU;
use std::time::{Duration, Instant};

use tiling_core::{Pose, Vec2};
use tiling_geometry::{
    AssemblyError, Conflicts, ContactTolerance, EdgeGraph, Placed, Shape, conflicts, signed_area,
    transform,
};

use crate::canonical::{Placement, Symmetry};
use crate::contact_dfs::{Options, Stats, solve};

/// Probes along each side of the target's bounding box, for stating overlaps
/// as cliques. Three millimetres apart on the corpus's 144 mm tray.
pub const PROBE_GRID: usize = 48;

/// Placements to choose from, and the constraints on the choice.
#[derive(Debug, Clone, PartialEq)]
pub struct Model {
    /// The classes of congruent pieces: for each, its members in piece order.
    /// A choice takes as many placements of a class as it has members.
    pub classes: Vec<Vec<usize>>,
    /// For each placement, the index of its class in `classes`.
    pub class_of: Vec<usize>,
    /// For each placement, a pose for each member of its class that puts that
    /// member there, in the order of the class's members.
    pub poses: Vec<Vec<Pose>>,
    /// The areas of the pieces add up to the target's, to within a boundary
    /// off by the length tolerance all the way round. Without this a choice
    /// with no conflict need not cover the target, and none is an assembly.
    pub areas_add_up: bool,
    /// What the placements exclude among themselves.
    pub conflicts: Conflicts,
    /// For each turn of the tray onto itself other than none, where it takes
    /// each placement: the index of the placement it becomes, if that one is
    /// in the model. A choice and its image under a turn are one assembly
    /// when the tray's rotations are counted once.
    pub turned: Vec<Vec<Option<u32>>>,
    /// The search that collected the placements ran to its end, so they are
    /// all of the reachable ones.
    pub exhausted: bool,
    /// The work of that search.
    pub search: Stats,
    /// How many assemblies that search found on its way. A chooser should
    /// find as many, counted the same way.
    pub search_solutions: usize,
    pub search_time: Duration,
    pub conflict_time: Duration,
}

/// Collect the placements the corner search reaches, and their conflicts.
///
/// `options` are the search's: its rules, whether the tray's rotations are
/// searched once or all, and its limits. `max_solutions` and
/// `collect_placements` are set here. With a limit reached, the model holds
/// what was collected so far and says so in `exhausted`. `targeted_probes`
/// is [`tiling_geometry::conflicts`]'s `targeted`.
pub fn reachable(
    target: Vec<Vec2>,
    shapes: Vec<Shape>,
    tolerance: ContactTolerance,
    options: &Options,
    targeted_probes: bool,
) -> Result<Model, AssemblyError> {
    let options = Options {
        max_solutions: None,
        collect_placements: true,
        ..options.clone()
    };
    let outcome = solve(target.clone(), shapes.clone(), tolerance, &options)?;

    let started = Instant::now();
    let pieces: f64 = shapes.iter().map(|s| signed_area(&s.polygon)).sum();
    let perimeter: f64 = (0..target.len())
        .map(|i| {
            let (p, q) = (target[i], target[(i + 1) % target.len()]);
            (q[0] - p[0]).hypot(q[1] - p[1])
        })
        .sum();
    let areas_add_up = (pieces - signed_area(&target)).abs() <= tolerance.length * perimeter;
    let graph = EdgeGraph::build(&shapes, &tolerance);
    let symmetry = Symmetry::new(&target, &shapes, &graph, &tolerance);
    let (model_classes, class_of, poses, placed) = lay_out(&symmetry, &shapes, &outcome.placements);
    let found = conflicts(&target, &placed, &tolerance, PROBE_GRID, targeted_probes);
    let turned = turned(&symmetry, &outcome.placements, &model_classes, &poses);
    Ok(Model {
        classes: model_classes,
        class_of,
        poses,
        areas_add_up,
        conflicts: found,
        turned,
        exhausted: outcome.exhausted,
        search: outcome.stats,
        search_solutions: outcome.solutions.len(),
        search_time: outcome.elapsed,
        conflict_time: started.elapsed(),
    })
}

type LaidOut = (Vec<Vec<usize>>, Vec<usize>, Vec<Vec<Pose>>, Vec<Placed>);

/// The classes, and for every placement its class, its poses and its polygon.
fn lay_out(symmetry: &Symmetry, shapes: &[Shape], placements: &[Placement]) -> LaidOut {
    let of_piece = symmetry.classes();
    // Classes in the order of their first pieces.
    let firsts: Vec<usize> = (0..shapes.len()).filter(|&p| of_piece[p] == p).collect();
    let classes: Vec<Vec<usize>> = firsts
        .iter()
        .map(|&first| {
            (0..shapes.len())
                .filter(|&p| of_piece[p] == first)
                .collect()
        })
        .collect();
    let mut class_of = Vec::with_capacity(placements.len());
    let mut poses = Vec::with_capacity(placements.len());
    let mut placed = Vec::with_capacity(placements.len());
    for placement in placements {
        let index = firsts
            .iter()
            .position(|&first| first == placement.class)
            .expect("a placement's class is the first piece of a class");
        let members: Vec<Pose> = classes[index]
            .iter()
            .map(|&piece| symmetry.pose_for(piece, placement))
            .collect();
        let first = placement.class;
        placed.push(Placed {
            world: transform(&shapes[first].polygon, &members[0]),
            roof: shapes[first].roof.map(|roof| (roof, members[0])),
        });
        class_of.push(index);
        poses.push(members);
    }
    (classes, class_of, poses, placed)
}

/// Where each turn of the tray takes each placement.
fn turned(
    symmetry: &Symmetry,
    placements: &[Placement],
    classes: &[Vec<usize>],
    poses: &[Vec<Pose>],
) -> Vec<Vec<Option<u32>>> {
    // Millimetres. Far above the tolerance, far below the size of a piece.
    const CELL: f64 = 0.01;
    let cell = |v: f64| (v / CELL).floor() as i64;
    let mut cells: HashMap<(usize, i64, i64), Vec<u32>> = HashMap::new();
    for (index, placement) in placements.iter().enumerate() {
        cells
            .entry((placement.class, cell(placement.x), cell(placement.y)))
            .or_default()
            .push(index as u32);
    }
    let [cx, cy] = symmetry.centre();
    let order = symmetry.tray_order();
    (1..order)
        .map(|step| {
            let angle = TAU * step as f64 / order as f64;
            let (s, c) = angle.sin_cos();
            placements
                .iter()
                .enumerate()
                .map(|(index, placement)| {
                    let first = classes
                        .iter()
                        .find(|members| members[0] == placement.class)
                        .expect("a placement's class is one of the classes")[0];
                    let pose = poses[index][0];
                    let (dx, dy) = (pose.x - cx, pose.y - cy);
                    let image = symmetry.placement(
                        first,
                        &Pose {
                            x: cx + c * dx - s * dy,
                            y: cy + s * dx + c * dy,
                            theta: pose.theta + angle,
                        },
                    );
                    let (ix, iy) = (cell(image.x), cell(image.y));
                    (-1..=1)
                        .flat_map(|dx| (-1..=1).map(move |dy| (dx, dy)))
                        .filter_map(|(dx, dy)| cells.get(&(image.class, ix + dx, iy + dy)))
                        .flatten()
                        .copied()
                        .find(|&other| symmetry.same_placement(&placements[other as usize], &image))
                })
                .collect()
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::contact_dfs::TrayRotations;
    use proptest::prelude::*;
    use tiling_geometry::testing::{TOL, Tiling, tiling};

    fn rectangle(w: f64, h: f64) -> Vec<Vec2> {
        vec![
            [-w / 2.0, -h / 2.0],
            [w / 2.0, -h / 2.0],
            [w / 2.0, h / 2.0],
            [-w / 2.0, h / 2.0],
        ]
    }

    fn bare(polygons: &[Vec<Vec2>]) -> Vec<Shape> {
        polygons
            .iter()
            .map(|polygon| Shape {
                polygon: polygon.clone(),
                roof: None,
            })
            .collect()
    }

    fn every_turn() -> Options {
        Options {
            tray_rotations: TrayRotations::All,
            anchor: false,
            ..Options::default()
        }
    }

    /// Every choice of one placement per class member with no conflict, by
    /// trying them all. For models of a handful of placements.
    fn choices(model: &Model) -> Vec<Vec<usize>> {
        let n = model.class_of.len();
        let mut excluded = vec![vec![false; n]; n];
        for &(a, b) in &model.conflicts.pairs {
            excluded[a as usize][b as usize] = true;
            excluded[b as usize][a as usize] = true;
        }
        for clique in &model.conflicts.cliques {
            for &a in clique {
                for &b in clique {
                    excluded[a as usize][b as usize] = a != b;
                }
            }
        }
        let need: Vec<usize> = model.classes.iter().map(Vec::len).collect();
        let mut found = Vec::new();
        fn extend(
            from: usize,
            chosen: &mut Vec<usize>,
            have: &mut Vec<usize>,
            need: &[usize],
            model: &Model,
            excluded: &[Vec<bool>],
            found: &mut Vec<Vec<usize>>,
        ) {
            if have == need {
                found.push(chosen.clone());
                return;
            }
            for next in from..model.class_of.len() {
                let class = model.class_of[next];
                if have[class] == need[class] || chosen.iter().any(|&c| excluded[c][next]) {
                    continue;
                }
                chosen.push(next);
                have[class] += 1;
                extend(next + 1, chosen, have, need, model, excluded, found);
                have[class] -= 1;
                chosen.pop();
            }
        }
        extend(
            0,
            &mut Vec::new(),
            &mut vec![0; need.len()],
            &need,
            model,
            &excluded,
            &mut found,
        );
        found
    }

    #[test]
    fn three_strips_have_a_placement_for_every_column_and_six_orders() {
        // Strips 2, 3 and 5 wide in a 10 x 12 tray, searched in both of its orientations.
        // They are too tall to lie down in it.
        let tray = vec![[0.0, 0.0], [10.0, 0.0], [10.0, 12.0], [0.0, 12.0]];
        let shapes = bare(&[
            rectangle(2.0, 12.0),
            rectangle(3.0, 12.0),
            rectangle(5.0, 12.0),
        ]);
        let model = reachable(tray, shapes, TOL, &every_turn(), false).unwrap();
        assert!(model.exhausted);
        assert_eq!(model.classes, [vec![0], vec![1], vec![2]]);
        // By hand. A strip stands with its left side at a sum of the widths of
        // the strips to its left. The 2 strip: 0, 3, 5, 8. The 3 strip: 0, 2,
        // 5, 7. The 5 strip: 0, 2, 3, 5. Twelve placements.
        assert_eq!(model.class_of.len(), 12);
        let mut lefts: Vec<Vec<f64>> = vec![Vec::new(); 3];
        for (placement, &class) in model.class_of.iter().enumerate() {
            let width = [2.0, 3.0, 5.0][class];
            let pose = model.poses[placement][0];
            lefts[class].push((pose.x - width / 2.0).round());
            assert!((pose.y - 6.0).abs() <= 1e-9);
        }
        for list in &mut lefts {
            list.sort_by(f64::total_cmp);
        }
        assert_eq!(
            lefts,
            [
                vec![0.0, 3.0, 5.0, 8.0],
                vec![0.0, 2.0, 5.0, 7.0],
                vec![0.0, 2.0, 3.0, 5.0]
            ]
        );
        // The search found the six orders, and so does choosing.
        assert_eq!(model.search_solutions, 6);
        assert_eq!(choices(&model).len(), 6);
    }

    #[test]
    fn a_turn_of_the_tray_takes_placements_to_placements() {
        // The strips again. A half turn of the 10 x 12 tray takes a strip with
        // its left side at x to one with its left side at 10 - width - x.
        let tray = vec![[0.0, 0.0], [10.0, 0.0], [10.0, 12.0], [0.0, 12.0]];
        let shapes = bare(&[
            rectangle(2.0, 12.0),
            rectangle(3.0, 12.0),
            rectangle(5.0, 12.0),
        ]);
        let model = reachable(tray, shapes, TOL, &every_turn(), false).unwrap();
        assert_eq!(model.turned.len(), 1);
        for (placement, image) in model.turned[0].iter().enumerate() {
            let image = image.expect("every column's mirror column is reachable") as usize;
            assert_eq!(model.class_of[image], model.class_of[placement]);
            let sum = model.poses[placement][0].x + model.poses[image][0].x;
            assert!((sum - 10.0).abs() <= 1e-9);
            // Turning twice is not turning.
            assert_eq!(model.turned[0][image], Some(placement as u32));
        }
        // By hand: the six orders are three pairs of mirror images.
        let found = choices(&model);
        let mirrored = |choice: &Vec<usize>| {
            let mut image: Vec<usize> = choice
                .iter()
                .map(|&p| model.turned[0][p].unwrap() as usize)
                .collect();
            image.sort_unstable();
            image
        };
        for choice in &found {
            assert_ne!(&mirrored(choice), choice);
            assert!(found.contains(&mirrored(choice)));
        }
    }

    #[test]
    fn pieces_too_small_for_the_tray_are_reported() {
        // 2 + 3 + 4 of strips for 10 of tray. With the pruning off the search
        // still stands them against the walls and one another, and three of
        // those placements can be chosen without conflict: not an assembly.
        let tray = vec![[0.0, 0.0], [10.0, 0.0], [10.0, 12.0], [0.0, 12.0]];
        let shapes = bare(&[
            rectangle(2.0, 12.0),
            rectangle(3.0, 12.0),
            rectangle(4.0, 12.0),
        ]);
        let options = Options {
            cavity_pruning: false,
            closure_pruning: false,
            ..every_turn()
        };
        let model = reachable(tray.clone(), shapes, TOL, &options, false).unwrap();
        assert!(!model.areas_add_up);
        assert_eq!(model.search_solutions, 0);
        assert!(!choices(&model).is_empty());
        // The strips of the other tests fill it.
        let shapes = bare(&[
            rectangle(2.0, 12.0),
            rectangle(3.0, 12.0),
            rectangle(5.0, 12.0),
        ]);
        assert!(
            reachable(tray, shapes, TOL, &options, false)
                .unwrap()
                .areas_add_up
        );
    }

    #[test]
    fn twins_share_their_placements() {
        // Two 2 x 4 strips, the second stored lying down, and a 4 x 4 block in an 8 x 4 tray.
        let tray = vec![[0.0, 0.0], [8.0, 0.0], [8.0, 4.0], [0.0, 4.0]];
        let shapes = bare(&[
            rectangle(2.0, 4.0),
            rectangle(4.0, 2.0),
            rectangle(4.0, 4.0),
        ]);
        let model = reachable(tray, shapes.clone(), TOL, &every_turn(), false).unwrap();
        assert_eq!(model.classes, [vec![0, 1], vec![2]]);
        // By hand: block left, middle or right, strips in the columns left over,
        // or lying one above the other beside the block.
        //   block at x in [0,4]: strips at [4,6] and [6,8], or lying at y in [0,2] and [2,4] over [4,8]
        //   block at [4,8]: likewise on the left
        //   block at [2,6]: strips at [0,2] and [6,8]
        // Five assemblies.
        assert_eq!(model.search_solutions, 5);
        let found = choices(&model);
        assert_eq!(found.len(), 5);
        // Each choice is two strip placements and one block placement, and a
        // pose is given for both twins that puts either on the same rectangle.
        for choice in &found {
            let strips: Vec<usize> = choice
                .iter()
                .copied()
                .filter(|&p| model.class_of[p] == 0)
                .collect();
            assert_eq!(strips.len(), 2);
            for &p in &strips {
                let first = transform(&shapes[0].polygon, &model.poses[p][0]);
                let second = transform(&shapes[1].polygon, &model.poses[p][1]);
                for corner in &first {
                    assert!(
                        second
                            .iter()
                            .any(|q| (q[0] - corner[0]).hypot(q[1] - corner[1]) <= 1e-9)
                    );
                }
            }
        }
    }

    #[test]
    fn a_limit_leaves_the_model_incomplete_and_says_so() {
        let tray = vec![[0.0, 0.0], [10.0, 0.0], [10.0, 6.0], [0.0, 6.0]];
        let shapes = bare(&[
            rectangle(2.0, 6.0),
            rectangle(3.0, 6.0),
            rectangle(5.0, 6.0),
        ]);
        let limited = Options {
            max_placements: Some(4),
            ..every_turn()
        };
        let model = reachable(tray, shapes, TOL, &limited, false).unwrap();
        assert!(!model.exhausted);
        assert_eq!(model.class_of.len(), 5);
    }

    proptest! {
        #![proptest_config(ProptestConfig::with_cases(48))]

        /// On a random tiling, choosing among the reachable placements gives
        /// as many assemblies as the search found, with the rules on or off.
        #[test]
        fn choosing_finds_what_the_search_found(tiling in tiling(), rules in any::<bool>()) {
            let Tiling { target, local: pieces, .. } = tiling;
            prop_assume!(pieces.len() <= 6);
            let options = Options {
                cavity_pruning: rules,
                closure_pruning: rules,
                ..every_turn()
            };
            let model = reachable(target, bare(&pieces), TOL, &options, false).unwrap();
            prop_assert!(model.exhausted);
            prop_assert!(model.search_solutions >= 1);
            prop_assume!(model.class_of.len() <= 60);
            prop_assert_eq!(choices(&model).len(), model.search_solutions);
        }
    }
}
