import numpy as np
from scipy.io import loadmat

from sklearn.externals.joblib import Memory, Parallel, delayed
from skimage import morphology
from skimage.segmentation import boundaries
#from skimage.measure import regionprops
from skimage.filter import sobel
from skimage.color import rgb2gray
from slic_python import slic_n

from datasets.pascal import PascalSegmentation
from latent_crf_experiments.utils import (gt_in_sp, region_graph,
                                          get_mean_colors, DataBunch,
                                          DataBunchNoSP, probabilities_on_sp)
from latent_crf_experiments.hierarchical_segmentation \
    import HierarchicalDataBunch


memory = Memory(cachedir="/tmp/cache")
pascal_path = "/home/local/datasets/VOC2011/TrainVal/VOCdevkit/VOC2011"
segments_path = ("/home/user/amueller/tools/cpmc_new/"
                 "cpmc_release1/data/MySegmentsMat")



def load_kraehenbuehl(filename):
    path = "/home/user/amueller/local/voc_potentials_kraehenbuehl/unaries/"
    with open(path + filename + ".unary") as f:
        size = np.fromfile(f, dtype=np.uint32, count=3).byteswap()
        data = np.fromfile(f, dtype=np.float32).byteswap()
        img = data.reshape(size[1], size[0], size[2])
    return img


@memory.cache
def load_pascal_pixelwise(which='train', year="2010"):
    pascal = PascalSegmentation()
    if which not in ["train", "val"]:
        raise ValueError("Expected 'which' to be 'train' or 'val', got %s." %
                         which)
    split_file = pascal_path + "/ImageSets/Segmentation/%s.txt" % which
    files = np.loadtxt(split_file, dtype=np.str)
    files = [f for f in files if f.split("_")[0] <= year]
    X, Y = [], []
    for f in files:
        X.append(load_kraehenbuehl(f))
        Y.append(pascal.get_ground_truth(f))

    return DataBunchNoSP(X, Y, files)


def load_pascal_single(f, sp_type, which, pascal):
        print(f)
        image = pascal.get_image(f)
        if sp_type == "slic":
            sp = slic_n(image, n_superpixels=100, compactness=10)
            segments = None
        elif sp_type == "cpmc":
            segments, sp = superpixels_segments(f)
            sp, _ = merge_small_sp(image, sp)
            sp = morphological_clean_sp(image, sp, 4)
        else:
            raise ValueError("Expected sp to be 'slic' or 'cpmc', got %s" %
                             sp_type)
        x = get_kraehenbuehl_pot_sp(f, sp)
        if which != "test":
            y = gt_in_sp(pascal, f, sp)
        return x, y, sp, segments


@memory.cache
def load_pascal(which='train', year="2010", sp_type="slic", n_jobs=-1):
    pascal = PascalSegmentation()
    files = pascal.get_split(which=which, year=year)
    results = Parallel(n_jobs=n_jobs)(delayed(load_pascal_single)(
        f, which=which, sp_type=sp_type, pascal=pascal) for f in files)
    X, Y, superpixels, segments = zip(*results)
    if sp_type == "slic":
        return DataBunch(X, Y, files, superpixels)
    else:
        return HierarchicalDataBunch(X, Y, files, superpixels, segments)


def get_kraehenbuehl_pot_sp(filename, superpixels):
    probs = load_kraehenbuehl(filename)
    ds = PascalSegmentation()
    return probabilities_on_sp(ds, probs, superpixels)


def superpixels_segments(filename):
    mat_file = segments_path + "/" + filename
    segments = loadmat(mat_file)['top_masks']
    n_segments = segments.shape[2]
    if n_segments > 100:
        raise ValueError("Need to rewrite... float only holds so many values.")
    # 2**50 + 1 is different from 2 ** 5. But 2 ** 50 + 2 ** -50 is not
    # different from 2 ** 50  so we do this in two stages
    added = (segments[:, :, :50] *
             2. ** np.arange(min(50, n_segments))).sum(axis=-1)
    _, added = np.unique(added, return_inverse=True)

    if n_segments > 50:
        added2 = (segments[:, :, 50:] *
                  2. ** np.arange(n_segments - 50)).sum(axis=-1)
        _, added2 = np.unique(added2, return_inverse=True)
        added = added + (np.max(added) + 1) * added2
        _, added = np.unique(added, return_inverse=True)

    labels = morphology.label(added.reshape(segments.shape[:2]), neighbors=4)

    return segments, labels


def get_pb(filename):
    pb = loadmat(segments_path[:-13] + "PB/" + filename +
                 "_PB.mat")['gPb_thin']
    return pb


def merge_small_sp(image, regions, min_size=None):
    if min_size is None:
        min_size = np.prod(image.shape[:2]) / float(np.max(regions) + 1)
    shape = regions.shape
    _, regions = np.unique(regions, return_inverse=True)
    regions = regions.reshape(shape[:2])
    edges = region_graph(regions)
    mean_colors = get_mean_colors(image, regions)
    mask = np.bincount(regions.ravel()) < min_size
    # mapping of old labels to new labels
    new_labels = np.arange(len(np.unique(regions)))
    for r in np.where(mask)[0]:
        # get neighbors:
        where_0 = edges[:, 0] == r
        where_1 = edges[:, 1] == r
        neighbors1 = edges[where_0, 1]
        neighbors2 = edges[where_1, 0]
        neighbors = np.concatenate([neighbors1, neighbors2])
        neighbors = neighbors[neighbors != r]
        # get closest in color
        distances = np.sum((mean_colors[r] - mean_colors[neighbors]) ** 2,
                           axis=-1)
        nearest = np.argmin(distances)
        # merge
        new = neighbors[nearest]
        new_labels[new_labels == r] = new
        edges[where_0, 0] = new
        edges[where_1, 1] = new
    regions = new_labels[regions]
    _, regions = np.unique(regions, return_inverse=True)
    regions = regions.reshape(shape[:2])
    grr = np.bincount(regions.ravel()) < min_size
    if np.any(grr):
        from IPython.core.debugger import Tracer
        Tracer()()
    return regions, new_labels


def morphological_clean_sp(image, segments, diameter=4):
    # remove small / thin segments by morphological closing + watershed
    # extract boundaries
    boundary = boundaries.find_boundaries(segments)
    closed = morphology.binary_closing(boundary, np.ones((diameter, diameter)))
    # extract regions
    labels = morphology.label(closed, neighbors=4, background=1)
    # watershed to get rid of boundaries
    # interestingly we can't use gPb here. It is to sharp.
    edge_image = sobel(rgb2gray(image))
    result = morphology.watershed(edge_image, labels + 1)
    # we want them to start at zero!
    return result - 1


def create_segment_sp_graph(segments, superpixels):
    #n_segments = segments.shape[2]
    n_superpixels = len(np.unique(superpixels))
    assert(n_superpixels == np.max(superpixels) + 1)
    edges = []
    for sp in range(n_superpixels):
        sp_indicator = superpixels == sp
        overlaps = segments[sp_indicator].sum(axis=0)
        includes = overlaps > np.sum(sp_indicator) / 2.
        for i in np.where(includes)[0]:
            edges.append([sp, i])
    return np.array(edges)


@memory.cache
def make_cpmc_hierarchy(dataset, data):
    X_new = []
    all_edges = Parallel(n_jobs=-1)(
        delayed(create_segment_sp_graph)(segments, superpixels)
        for superpixels, segments in zip(data.superpixels, data.segments))
    for x, superpixels, segments, edges in zip(data.X, data.superpixels,
                                               data.segments, all_edges):
        n_superpixels = len(np.unique(superpixels))
        n_segments = segments.shape[2]
        edges[:, 1] += n_superpixels
        X_new.append((x, edges, n_segments))
    return HierarchicalDataBunch(X_new, data.Y, data.file_names,
                                 data.superpixels, data.segments)
