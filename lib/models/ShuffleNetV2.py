import functools

import torch
import torch.nn as nn

__all__ = ['ShuffleNetV2']


def channel_shuffle(x, groups):
  batchsize, num_channels, height, width = x.data.size()
  channels_per_group = num_channels // groups

  # reshape
  x = x.view(batchsize, groups, channels_per_group, height, width)

  x = torch.transpose(x, 1, 2).contiguous()

  # flatten
  x = x.view(batchsize, -1, height, width)

  return x


class InvertedResidual(nn.Module):
  def __init__(self, inp, oup, stride):
    super(InvertedResidual, self).__init__()

    if not (1 <= stride <= 3):
      raise ValueError('illegal stride value')
    self.stride = stride

    branch_features = oup // 2
    assert (self.stride != 1) or (inp == branch_features << 1)

    pw_conv11 = functools.partial(nn.Conv2d, kernel_size=1, stride=1, padding=0, bias=False)
    dw_conv33 = functools.partial(self.depthwise_conv, kernel_size=3, stride=self.stride, padding=1)

    if self.stride > 1:
      self.branch1 = nn.Sequential(
        dw_conv33(inp, inp),
        nn.BatchNorm2d(inp),
        pw_conv11(inp, branch_features),
        nn.BatchNorm2d(branch_features),
        nn.ReLU(inplace=True),
      )

    self.branch2 = nn.Sequential(
      pw_conv11(inp if (self.stride > 1) else branch_features, branch_features),
      nn.BatchNorm2d(branch_features),
      nn.ReLU(inplace=True),
      dw_conv33(branch_features, branch_features),
      nn.BatchNorm2d(branch_features),
      pw_conv11(branch_features, branch_features),
      nn.BatchNorm2d(branch_features),
      nn.ReLU(inplace=True),
    )

  @staticmethod
  def depthwise_conv(i, o, kernel_size, stride=1, padding=0, bias=False):
    return nn.Conv2d(i, o, kernel_size, stride, padding, bias=bias, groups=i)

  def forward(self, x):
    if self.stride == 1:
      x1, x2 = x.chunk(2, dim=1)
      out = torch.cat((x1, self.branch2(x2)), dim=1)
    else:
      out = torch.cat((self.branch1(x), self.branch2(x)), dim=1)

    out = channel_shuffle(out, 2)
    return out


class ShuffleNetV2(nn.Module):
  def __init__(self, num_classes, stages):
    super(ShuffleNetV2, self).__init__()

    self.stage_out_channels = stages
    assert len(stages) == 5, 'invalid stages : {:}'.format(stages)
    self.message = 'stages: ' + ' '.join([str(x) for x in stages])

    input_channels = 3
    output_channels = self.stage_out_channels[0]
    self.conv1 = nn.Sequential(
      nn.Conv2d(input_channels, output_channels, 3, 2, 1, bias=False),
      nn.BatchNorm2d(output_channels),
      nn.ReLU(inplace=True),
    )
    input_channels = output_channels

    self.maxpool = nn.MaxPool2d(kernel_size=3, stride=2, padding=1)

    stage_names = ['stage{:}'.format(i) for i in [2, 3, 4]]
    stage_repeats = [4, 8, 4]
    for name, repeats, output_channels in zip(
        stage_names, stage_repeats, self.stage_out_channels[1:]):
      seq = [InvertedResidual(input_channels, output_channels, 2)]
      for i in range(repeats - 1):
        seq.append(InvertedResidual(output_channels, output_channels, 1))
      setattr(self, name, nn.Sequential(*seq))
      input_channels = output_channels

    output_channels = self.stage_out_channels[-1]
    self.conv5 = nn.Sequential(
      nn.Conv2d(input_channels, output_channels, 1, 1, 0, bias=False),
      nn.BatchNorm2d(output_channels),
      nn.ReLU(inplace=True),
    )

    self.fc = nn.Linear(output_channels, num_classes)

  def get_message(self):
    return self.message

  def forward(self, inputs):
    x = self.conv1( inputs )
    x = self.maxpool(x)
    x = self.stage2(x)
    x = self.stage3(x)
    x = self.stage4(x)
    x = self.conv5(x)
    features = x.mean([2, 3])  # globalpool
    predicts = self.fc(features)
    return features, predicts

  #@staticmethod
  #def _getStages(mult):
  #  stages = {
  #    '0.5': [24, 48,  96 , 192, 1024],
  #    '1.0': [24, 116, 232, 464, 1024],
  #    '1.5': [24, 176, 352, 704, 1024],
  #    '2.0': [24, 244, 488, 976, 2048],
  #  }
  #  return stages[str(mult)]