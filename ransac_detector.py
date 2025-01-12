import open3d as o3d
import numpy as np
import copy
from typing import Callable, List, Tuple
import cv2
import random
from functools import reduce

DEFAULT_SHAPE = (640, 480)
DEFAULT_CAM = o3d.camera.PinholeCameraIntrinsic(
    o3d.camera.PinholeCameraIntrinsicParameters.PrimeSenseDefault)


def crop_depth_map(depth_map: np.array, threshold=np.mean) -> Tuple[np.array, int]:
    """
    Function to crop pixel with big depth
    :param depth_map: input depth map
    :param threshold: function, float or int
    :return: croped depth map, number of nonzero pixels
    """
    vect_func = np.vectorize(lambda x: 1 / x if x > 0 else x)
    tmp = vect_func(depth_map)
    if isinstance(threshold, Callable):
        arr = tmp.flatten()
        t = threshold(arr[arr > 0])
    else:
        t = threshold
    ans = np.where(tmp < t, tmp, 0)
    return ans, len(np.argwhere(ans))


def get_connected_components(depth_map: np.array, threshold=0.3) -> List[np.array]:
    """
    Function to split depth map into separated components
    :param depth_map: input depth map
    :param threshold: float, components, which less then this value, will be skipped
    :return: list of depth maps
    """
    arr = np.uint8(np.where(depth_map > 0, 1, 0))
    count_pixels = arr.sum()
    num, result = cv2.connectedComponents(arr)
    ans = []
    for i in range(1, num):
        map_arr = np.where(result == i, 1, 0)
        if map_arr.sum() >= threshold * count_pixels:
            ans.append((np.float32(depth_map * map_arr), map_arr))
    return ans


def _get_plane_from_pcd(depth_map: np.array):
    """
    Returns plane and indeces of inliers from depth_map
    :param depth_map: initial depth_map
    :return: plane params and list of indeces
    """
    img_3d = o3d.geometry.Image(np.float32(depth_map))
    pcd = o3d.geometry.PointCloud.create_from_depth_image(img_3d, DEFAULT_CAM)
    pcd.transform([[1, 0, 0, 0], [0, -1, 0, 0], [0, 0, -1, 0], [0, 0, 0, 1]])
    arr = np.asarray(pcd.points)
    th = abs(np.max(arr) - np.min(arr)) / 100
    plane_model, inliers = pcd.segment_plane(distance_threshold=th,
                                             ransac_n=3,
                                             num_iterations=100)
    return plane_model, inliers


def extract_planes_con(map_arr: np.array, depth_map: np.array, start_size: int, t: float) -> List[np.array]:
    """
    Extracts planes from depth_map
    :param map_arr: mask for segment of image
    :param depth_map: depth for this segment
    :param start_size: initial count of ponts in point cloud
    :param t: threshold for time until method extracts planes
    :return: list of map_arrs and plane params from pcd
    """
    curr_map_arr = copy.deepcopy(map_arr)
    count = start_size
    result = []
    while count >= int(start_size * t):
        plane_model, inliers = _get_plane_from_pcd(depth_map * curr_map_arr)
        ls = np.where(curr_map_arr)
        ans = np.zeros(curr_map_arr.shape)
        x, y = ls[0][inliers], ls[1][inliers]
        curr_map_arr[x, y] = 0
        ans[x, y] = 1
        result.append((ans, plane_model))
        count -= len(inliers)
    return result


def get_plane_img(img: np.array, ls_map_arrs: List[np.array]) -> np.array:
    """
    Function to plot detected planes on picture
    :param img:
    :param ls_map_arrs:
    :return:
    """
    res = copy.deepcopy(img)
    for map_arr in ls_map_arrs:
        color = [random.randint(1, 255) for _ in range(3)]
        ind = np.where(map_arr)
        res[ind[0], ind[1], :] = color
    return res


def close_map(map_arr: np.array, kernels=None) -> np.array:
    """
    Function used for filling holes in map_arr
    :param map_arr: initial map_arr
    :param kernels: tuple of kernels used to fill holes in map
    :return: resulting map_arr after closing
    """
    if kernels is None:
        kernels = [np.ones((100, 10), np.uint8), np.ones((10, 100), np.uint8)]

    ls_closings = [cv2.morphologyEx(np.uint8(map_arr), cv2.MORPH_CLOSE, kernel) for kernel in kernels]
    return reduce(np.logical_and, ls_closings, np.ones(map_arr.shape))


def loss_metric(true_pcd: o3d.geometry.PointCloud, approx_pcd: o3d.geometry.PointCloud, func="rmse") -> float:
    """
    :param true_pcd:
    :param approx_pcd:
    :param func:
    :return:
    """
    funcs = {
        "rmse": (lambda x, y: ((x - y) * 1000) ** 2, lambda x, n: np.sqrt(x / n)),
        "mae": (lambda x, y: abs((x - y) * 1000), lambda x, n: x / n),
        "mse": (lambda x, y: ((x - y) * 1000) ** 2, lambda x, n: x / n)
    }
    true_arr = np.asarray(true_pcd.points)
    approx_arr = np.asarray(approx_pcd.points)
    loss = 0
    for x, y in zip(true_arr, approx_arr):
        loss += funcs[func][0](x[-1], y[-1])
    return funcs[func][1](loss, len(true_arr))