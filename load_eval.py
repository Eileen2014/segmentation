#!/usr/bin/python
import sys

import matplotlib.pyplot as plt
import numpy as np


#from sklearn.metrics import confusion_matrix

from pystruct.utils import SaveLogger
from pystruct.models import LatentNodeCRF

from msrc import msrc_helpers
from pascal import pascal_helpers
from nyu import nyu_helpers
from latent_crf_experiments.hierarchical_segmentation import \
    make_hierarchical_data

from datasets.msrc import MSRC21Dataset
from datasets.pascal import PascalSegmentation
from datasets.nyu import NYUSegmentation

from utils import add_edges, eval_on_sp, add_edge_features
from plotting import plot_results



def main():
    argv = sys.argv
    print("loading %s ..." % argv[1])
    ssvm = SaveLogger(file_name=argv[1]).load()
    if hasattr(ssvm, 'problem'):
        ssvm.model = ssvm.problem
    print(ssvm)
    if hasattr(ssvm, 'base_ssvm'):
        ssvm = ssvm.base_ssvm
    print("Iterations: %d" % len(ssvm.objective_curve_))
    print("Objective: %f" % ssvm.objective_curve_[-1])
    inference_run = None
    if hasattr(ssvm, 'cached_constraint_'):
        inference_run = ~np.array(ssvm.cached_constraint_)
        print("Gap: %f" %
              (np.array(ssvm.primal_objective_curve_)[inference_run][-1] -
               ssvm.objective_curve_[-1]))

    if len(argv) <= 2:
        argv.append("acc")

    if len(argv) <= 3:
        dataset = 'nyu'
    else:
        dataset = argv[3]

    if argv[2] == 'acc':

        ssvm.n_jobs = 1

        for data_str, title in zip(["train", "val"],
                                   ["TRAINING SET", "VALIDATION SET"]):
            print(title)
            edge_type = "pairwise"

            if dataset == 'msrc':
                ds = MSRC21Dataset()
                data = msrc_helpers.load_data(data_str, which="piecewise_new")
                #data = add_kraehenbuehl_features(data, which="train_30px")
                data = msrc_helpers.add_kraehenbuehl_features(data, which="train")
            elif dataset == 'pascal':
                ds = PascalSegmentation()
                data = pascal_helpers.load_pascal(data_str, sp_type="cpmc")
                #data = pascal_helpers.load_pascal(data_str)
            elif dataset == 'nyu':
                ds = NYUSegmentation()
                data = nyu_helpers.load_nyu(data_str, n_sp=500, sp='rgbd')
            else:
                raise ValueError("Excepted dataset to be 'nyu', 'pascal' or 'msrc',"
                                 " got %s." % dataset)

            if type(ssvm.model).__name__ == "LatentNodeCRF":
                print("making data hierarchical")
                data = pascal_helpers.make_cpmc_hierarchy(ds, data)
                #data = make_hierarchical_data(
                    #ds, data, lateral=True, latent=True, latent_lateral=False,
                    #add_edge_features=False)
            else:
                data = add_edges(data, edge_type)

            if type(ssvm.model).__name__ == 'EdgeFeatureGraphCRF':
                data = add_edge_features(ds, data, depth_diff=True, normal_angles=True)

            if type(ssvm.model).__name__ == "EdgeFeatureLatentNodeCRF":
                data = add_edge_features(ds, data)
                data = make_hierarchical_data(
                    ds, data, lateral=True, latent=True, latent_lateral=False,
                    add_edge_features=True)
            #ssvm.model.inference_method = "qpbo"
            Y_pred = ssvm.predict(data.X)

            if isinstance(ssvm.model, LatentNodeCRF):
                Y_pred = [ssvm.model.label_from_latent(h) for h in Y_pred]
            Y_flat = np.hstack(data.Y)

            print("superpixel accuracy: %.2f"
                  % (np.mean((np.hstack(Y_pred) == Y_flat)[Y_flat != ds.void_label]) * 100))

            if dataset == 'msrc':
                res = msrc_helpers.eval_on_pixels(data, Y_pred,
                                                  print_results=True)
                print("global: %.2f, average: %.2f" % (res['global'] * 100,
                                                       res['average'] * 100))
                #msrc_helpers.plot_confusion_matrix(res['confusion'])
            else:
                hamming, jaccard = eval_on_sp(ds, data, Y_pred,
                                              print_results=True)
                print("Jaccard: %.2f, Hamming: %.2f" % (jaccard.mean(),
                                                        hamming.mean()))

        plt.show()

    elif argv[2] == 'plot':
        data_str = 'val'
        if len(argv) <= 4:
            raise ValueError("Need a folder name for plotting.")
        if dataset == "msrc":
            ds = MSRC21Dataset()
            data = msrc_helpers.load_data(data_str, which="piecewise")
            data = add_edges(data, independent=False)
            data = msrc_helpers.add_kraehenbuehl_features(
                data, which="train_30px")
            data = msrc_helpers.add_kraehenbuehl_features(
                data, which="train")

        elif dataset == "pascal":
            ds = PascalSegmentation()
            data = pascal_helpers.load_pascal("val")
            data = add_edges(data)

        elif dataset == "nyu":
            ds = NYUSegmentation()
            data = nyu_helpers.load_nyu("test")
            data = add_edges(data)

        if type(ssvm.model).__name__ == 'EdgeFeatureGraphCRF':
            data = add_edge_features(ds, data, depth_diff=True, normal_angles=True)
        Y_pred = ssvm.predict(data.X)

        plot_results(ds, data, Y_pred, argv[4])


if __name__ == "__main__":
    main()
