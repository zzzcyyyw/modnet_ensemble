import os
import sys
import argparse
import numpy as np
from PIL import Image

import torch
import torch.nn as nn
import torch.nn.functional as F
import torchvision.transforms as transforms
import sys
import os 
from srcs.models.modnet_ensemble_v2 import EnsembleMODNet
from utils import compute_mse, compute_sad, AverageMeter      # zc
from collections import OrderedDict
# import modnet.MODNet


if __name__ == '__main__':
    # define cmd arguments
    parser = argparse.ArgumentParser()
    parser.add_argument('--input-path', type=str, default='data/Distinctions-646/Test/Comp/', help='path of input images')
    parser.add_argument('--output-path', type=str, default='data/Distinctions-646/Test/matte_out/', help='path of output images')
    parser.add_argument('--GT-path', type=str, default='data/Distinctions-646/Test/GT/', help='path of GT images')      # zc增加
    args = parser.parse_args()

    # check input arguments
    if not os.path.exists(args.input_path):
        print('Cannot find input path: {0}'.format(args.input_path))
        exit()
    if not os.path.exists(args.output_path):
        os.makedirs(args.output_path)
    

    # define hyper-parameters
    ref_size = 512
    mode_save_dir = "saved_model/ensemble_v2/Ensemble_38.pth"
    

    # define image to tensor transform
    im_transform = transforms.Compose(
        [
            transforms.ToTensor(),
            transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5))
        ]
    )

    # create MODNet and load the pre-trained ckpt
    modnet = EnsembleMODNet(backbone_pretrained=False, ensemble_size=3)
    ckpt = torch.load(mode_save_dir, map_location='cpu')
    modnet.load_state_dict({k.replace('module.', ''): v for k, v in ckpt.items()})
    
    #modnet.load_state_dict(ckpt)
    modnet.eval()

    mse_losses = AverageMeter()     # zc
    sad_losses = AverageMeter()     # zc
    
    # inference images
    im_names = os.listdir(args.input_path)
    for im_name in im_names:
        file_name = im_name.split('.')
        file_name = file_name[-1]
        if file_name != 'jpg' and file_name != 'png':
            continue

        print('Process image: {0}'.format(im_name))

        alpha_name = im_name.split('--Fotor--')[0]
        alpha = Image.open(os.path.join(args.GT_path, alpha_name))
        alpha = alpha.convert('L')
        alpha = np.asarray(alpha)
        alpha = alpha / 255.

        # read image
        im = Image.open(os.path.join(args.input_path, im_name))

        # unify image channels to 3
        im = np.asarray(im)
        if len(im.shape) == 2:
            im = im[:, :, None]
        if im.shape[2] == 1:
            im = np.repeat(im, 3, axis=2)
        elif im.shape[2] == 4:
            im = im[:, :, 0:3]

        # convert image to PyTorch tensor
        im = Image.fromarray(im)
        im = im_transform(im)

        # add mini-batch dim
        im = im[None, :, :, :]

        # resize image for input
        im_b, im_c, im_h, im_w = im.shape
        if max(im_h, im_w) < ref_size or min(im_h, im_w) > ref_size:
            if im_w >= im_h:
                im_rh = ref_size
                im_rw = int(im_w / im_h * ref_size)
            elif im_w < im_h:
                im_rw = ref_size
                im_rh = int(im_h / im_w * ref_size)
        else:
            im_rh = im_h
            im_rw = im_w
        
        im_rw = im_rw - im_rw % 32
        im_rh = im_rh - im_rh % 32
        im = F.interpolate(im, size=(im_rh, im_rw), mode='area')

        # inference
        _, _, mattes = modnet(im, True)

        # resize and save matte
        matte_avg = np.zeros((im_h, im_w), dtype=np.float32)        # zc
        for i, matte in enumerate(mattes):
            matte = F.interpolate(matte, size=(im_h, im_w), mode='area')
            matte = matte[0][0].data.cpu().numpy()
            # matte_name = im_name.split('.')[0] + str(i) + '.png'
            # Image.fromarray(((matte * 255).astype('uint8')), mode='L').save(os.path.join(args.output_path, matte_name))
            matte_avg += matte

        matte_avg = matte_avg / 3.
        Image.fromarray(((matte_avg * 255).astype('uint8')), mode='L').save(os.path.join(args.output_path, im_name))
        mse_loss = compute_mse(matte_avg, alpha)
        sad_loss = compute_sad(matte_avg, alpha)
        # Keep track of metrics
        mse_losses.update(mse_loss.item())
        sad_losses.update(sad_loss.item())
        print("sad:{} mse:{}".format(sad_loss.item(), mse_loss.item()))
        print("avg_sad:{} avg_mse:{}".format(sad_losses.avg, mse_losses.avg))
    print("fin_sad:{} fin_mse:{}".format(sad_losses.avg, mse_losses.avg))

