# Copyright 2017 Google Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import sys

# internal imports
import numpy as np
import tensorflow as tf
import librosa
from magenta.models.nsynth import utils

FLAGS = tf.app.flags.FLAGS

tf.app.flags.DEFINE_string("expdir", "",
                           "The log directory for this experiment. Required if "
                           "`checkpoint_path` is not given.")
tf.app.flags.DEFINE_string("checkpoint_path", "",
                           "A path to the checkpoint. If not given, the latest "
                           "checkpoint in `expdir` will be used.")
tf.app.flags.DEFINE_string("wavdir", "",
                           "The directory of WAVs to yield embeddings from.")
tf.app.flags.DEFINE_string("config", "model", "Model configuration name")
tf.app.flags.DEFINE_integer("sample_length", 64000, "Sample length.")
tf.app.flags.DEFINE_integer("batch_size", 16, "Sample length.")

tf.app.flags.DEFINE_string("wav_savedir", "", "Where to save the generated wav files.")
tf.app.flags.DEFINE_integer("sample_rate", 16000, "Sample length.")
tf.app.flags.DEFINE_string("log", "INFO",
                           "The threshold for what messages will be logged."
                           "DEBUG, INFO, WARN, ERROR, or FATAL.")

def mu_law_decode(output, quantization_channels):
    '''Recovers waveform from quantized values.'''
    with tf.name_scope('decode'):
        mu = quantization_channels - 1
        # Map values back to [-1, 1].
        signal = 2 * (tf.to_float(output) / mu) - 1
        # Perform inverse of mu-law transformation.
        magnitude = (1 / mu) * ((1 + mu)**abs(signal) - 1)
        return tf.sign(signal) * magnitude

def write_wav(waveform, sample_rate, pathname):
    y = np.array(waveform)
    librosa.output.write_wav(filename, y, sample_rate)
    print('Updated wav file at {}'.format(pathname))

def generate(prediction):
  decoded_prediction = mu_law_decode(prediction, 256)
  write_wav(decoded_prediction, sample_rate, FLAGS.wav_savedir)

def main(unused_argv=None):
  tf.logging.set_verbosity(FLAGS.log)
  
  if FLAGS.config is None:
    raise RuntimeError("No config name specified.")

  config = utils.get_module("ours." + FLAGS.config).Config()

  if FLAGS.checkpoint_path:
    checkpoint_path = FLAGS.checkpoint_path
  else:
    expdir = FLAGS.expdir
    tf.logging.info("Will load latest checkpoint from %s.", expdir)
    while not tf.gfile.Exists(expdir):
      tf.logging.fatal("\tExperiment save dir '%s' does not exist!", expdir)
      sys.exit(1)

    try:
      checkpoint_path = tf.train.latest_checkpoint(expdir)
    except tf.errors.NotFoundError:
      tf.logging.fatal("There was a problem determining the latest checkpoint.")
      sys.exit(1)

  if not tf.train.checkpoint_exists(checkpoint_path):
    tf.logging.fatal("Invalid checkpoint path: %s", checkpoint_path)
    sys.exit(1)

  tf.logging.info("Will restore from checkpoint: %s", checkpoint_path)

  wavdir = FLAGS.wavdir
  tf.logging.info("Will load Wavs from %s." % wavdir)

  ######################
  # restore the model  #
  ######################
  tf.logging.info("Building graph")
  with tf.Graph().as_default():
    total_batch_size = FLAGS.total_batch_size
    assert total_batch_size % FLAGS.worker_replicas == 0
    worker_batch_size = total_batch_size / FLAGS.worker_replicas

    # Run the Reader on the CPU
    cpu_device = "/job:localhost/replica:0/task:0/cpu:0"
    if FLAGS.ps_tasks:
      cpu_device = "/job:worker/cpu:0"

    with tf.device(cpu_device):
      inputs_dict = config.get_batch(worker_batch_size)

      # build the model graph
      encode_dict = config.encode(inputs_dict["wav"])
      decode_dict = config.decode(encode_dict["encoding"])
      loss_dict = config.loss(encode_dict["x_quantized"], decode_dict["logits"])
      loss = loss_dict["loss"]
      
      generate_wav = generate(decode_dict["predicitons"])
      # decode_dict["predictions"] = tf.placeholder("float", [None, 256])

      init = tf.global_variables_initializer()
      session_config = tf.ConfigProto(allow_soft_placement=True) #?
      saver = tf.train.Saver()
      with tf.Session("", config=session_config) as sess:
        sess.run(init) 
        tf.logging.info("\tRestoring from checkpoint.")
        saver.restore(sess, checkpoint_path)

        wav_savedir = FLAGS.wav_savedir
        tf.logging.info("Will save wav files to %s." % wav_savedir)
        if not tf.gfile.Exists(wav_savedir):
          tf.logging.info("Creating save directory...")
          tf.gfile.MakeDirs(wav_savedir)
 
        sess.run(generate_wav)

if __name__ == "__main__":
  tf.app.run()
