# ------------------------------------------------------------------------
# Copyright (c) 2022 megvii-model. All Rights Reserved.
# ------------------------------------------------------------------------
import mmcv
import numpy as np
from mmdet.datasets.builder import PIPELINES

@PIPELINES.register_module()
class LoadMultiViewImageFromMultiSweepsFiles(object):
    """Load multi channel images from a list of separate channel files.
    Expects results['img_filename'] to be a list of filenames.
    Args:
        to_float32 (bool): Whether to convert the img to float32.
            Defaults to False.
        color_type (str): Color type of the file. Defaults to 'unchanged'.
    """

    def __init__(self, 
                sweeps_num=5,
                to_float32=False, 
                file_client_args=dict(backend='disk'),
                pad_empty_sweeps=False,
                sweep_range=[3,27],
                sweeps_id = None,
                color_type='unchanged',
                sensors = ['CAM_FRONT', 'CAM_FRONT_RIGHT', 'CAM_FRONT_LEFT', 'CAM_BACK', 'CAM_BACK_LEFT', 'CAM_BACK_RIGHT'],
                test_mode=True,
                prob=1.0,
                ):

        self.sweeps_num = sweeps_num # 1    
        self.to_float32 = to_float32 # True
        self.color_type = color_type # 'unchanged'
        self.file_client_args = file_client_args.copy() # dict(backend='disk')
        self.file_client = None # None
        self.pad_empty_sweeps = pad_empty_sweeps # True
        self.sensors = sensors # ['CAM_FRONT', 'CAM_FRONT_RIGHT', 'CAM_FRONT_LEFT', 'CAM_BACK', 'CAM_BACK_LEFT', 'CAM_BACK_RIGHT']
        self.test_mode = test_mode # False
        self.sweeps_id = sweeps_id # None
        self.sweep_range = sweep_range # [3, 27]
        self.prob = prob # 1.0
        if self.sweeps_id:
            assert len(self.sweeps_id) == self.sweeps_num

    def __call__(self, results):
        """Call function to load multi-view image from files.
        Args:
            results (dict): Result dict containing multi-view image filenames.
        Returns:
            dict: The result dict containing the multi-view image data. \
                Added keys and values are described below.
                - filename (str): Multi-view image filenames.
                - img (np.ndarray): Multi-view image arrays.
                - img_shape (tuple[int]): Shape of multi-view image arrays.
                - ori_shape (tuple[int]): Shape of original image arrays.
                - pad_shape (tuple[int]): Shape of padded image arrays.
                - scale_factor (float): Scale factor.
                - img_norm_cfg (dict): Normalization configuration of images.
        """
        sweep_imgs_list = []
        timestamp_imgs_list = []
        imgs = results['img'] # (6, 900, 1600, 3)
        img_timestamp = results['img_timestamp'] # List[6个img时间戳]
        lidar_timestamp = results['timestamp'] # lidar时间戳
        img_timestamp = [lidar_timestamp - timestamp for timestamp in img_timestamp] # 计算lidar和img的时间差
        sweep_imgs_list.extend(imgs) # 加入当前帧图片
        timestamp_imgs_list.extend(img_timestamp) # 加入当前帧时间戳
        nums = len(imgs) # 6
        # 如果没有prev帧，则pad空帧
        if self.pad_empty_sweeps and len(results['sweeps']) == 0:
            for i in range(self.sweeps_num): # 1
                sweep_imgs_list.extend(imgs) # 重复当前帧
                mean_time = (self.sweep_range[0] + self.sweep_range[1]) / 2.0 * 0.083 # 平均时间
                timestamp_imgs_list.extend([time + mean_time for time in img_timestamp]) # 当前时间戳的基础上增加平均时间
                for j in range(nums):
                    results['filename'].append(results['filename'][j]) # lidar路径
                    results['lidar2img'].append(np.copy(results['lidar2img'][j])) # lidar到img的变换矩阵
                    results['intrinsics'].append(np.copy(results['intrinsics'][j])) # 内参
                    results['extrinsics'].append(np.copy(results['extrinsics'][j])) # 外参
        else:
            if self.sweeps_id: # None
                choices = self.sweeps_id
            elif len(results['sweeps']) <= self.sweeps_num:
                choices = np.arange(len(results['sweeps']))
            elif self.test_mode:
                choices = [int((self.sweep_range[0] + self.sweep_range[1])/2) - 1] 
            else:
                if np.random.random() < self.prob:
                    if self.sweep_range[0] < len(results['sweeps']):
                        # 根据帧数更新sweep的范围
                        sweep_range = list(range(self.sweep_range[0], min(self.sweep_range[1], len(results['sweeps']))))
                    else:
                        sweep_range = list(range(self.sweep_range[0], self.sweep_range[1]))
                    choices = np.random.choice(sweep_range, self.sweeps_num, replace=False) # 在sweep范围内随机选择一帧 eg:14
                else:
                    choices = [int((self.sweep_range[0] + self.sweep_range[1])/2) - 1] 
                
            for idx in choices:
                sweep_idx = min(idx, len(results['sweeps']) - 1) # eg:14
                sweep = results['sweeps'][sweep_idx] # 读取该sweep的info, 包含6个cam的info
                if len(sweep.keys()) < len(self.sensors):
                    sweep = results['sweeps'][sweep_idx - 1]
                results['filename'].extend([sweep[sensor]['data_path'] for sensor in self.sensors]) # 读取图片路径并且extend到results['filename']
                # 读取图片 (900, 1600, 3, 6)
                img = np.stack([mmcv.imread(sweep[sensor]['data_path'], self.color_type) for sensor in self.sensors], axis=-1)
                
                if self.to_float32:
                    img = img.astype(np.float32)
                img = [img[..., i] for i in range(img.shape[-1])]
                sweep_imgs_list.extend(img) # 将图片extend到sweep_imgs_list
                # 计算curr帧lidar时间戳和prev帧图片的时间差
                sweep_ts = [lidar_timestamp - sweep[sensor]['timestamp'] / 1e6  for sensor in self.sensors]
                timestamp_imgs_list.extend(sweep_ts) # 扩展时间戳
                for sensor in self.sensors:
                    results['lidar2img'].append(sweep[sensor]['lidar2img']) # 增加lidar2img的变换矩阵, 均是T帧的lidar到T-n帧的img的变换
                    results['intrinsics'].append(sweep[sensor]['intrinsics']) # 增加相机内参
                    results['extrinsics'].append(sweep[sensor]['extrinsics']) # 增加lidar2cam的变换矩阵
        results['img'] = sweep_imgs_list # 记录2帧的img
        results['timestamp'] = timestamp_imgs_list # 记录两帧的timestamp

        return results

    def __repr__(self):
        """str: Return a string that describes the module."""
        repr_str = self.__class__.__name__
        repr_str += f'(to_float32={self.to_float32}, '
        repr_str += f"color_type='{self.color_type}')"
        return repr_str
