import React from "react";
import { Composition, Series, staticFile, useVideoConfig } from "remotion";
import { Audio } from "@remotion/media";
import { BAR } from "./kit";
import { Hook } from "./scenes/Hook";
import { Clock } from "./scenes/Clock";
import { Money } from "./scenes/Money";
import { Shock } from "./scenes/Shock";
import { Tape } from "./scenes/Tape";
import { Product } from "./scenes/Product";
import { Call } from "./scenes/Call";
import { Trust } from "./scenes/Trust";
import { End } from "./scenes/End";

// 25 bars at 120 BPM = 50 s; every cut is on a bar line of music/make_track.py.
export const Launch: React.FC = () => {
  const { fps } = useVideoConfig();
  return (
    <>
      <Series>
        <Series.Sequence name="Hook" durationInFrames={4 * BAR} premountFor={fps}>
          <Hook />
        </Series.Sequence>
        <Series.Sequence name="Clock" durationInFrames={2 * BAR} premountFor={fps}>
          <Clock />
        </Series.Sequence>
        <Series.Sequence name="Money" durationInFrames={3 * BAR} premountFor={fps}>
          <Money />
        </Series.Sequence>
        <Series.Sequence name="Shock" durationInFrames={3 * BAR} premountFor={fps}>
          <Shock />
        </Series.Sequence>
        <Series.Sequence name="Tape" durationInFrames={3 * BAR} premountFor={fps}>
          <Tape />
        </Series.Sequence>
        <Series.Sequence name="Product" durationInFrames={3 * BAR} premountFor={fps}>
          <Product />
        </Series.Sequence>
        <Series.Sequence name="Call" durationInFrames={3 * BAR} premountFor={fps}>
          <Call />
        </Series.Sequence>
        <Series.Sequence name="Trust" durationInFrames={2 * BAR} premountFor={fps}>
          <Trust />
        </Series.Sequence>
        <Series.Sequence name="End" durationInFrames={2 * BAR} premountFor={fps}>
          <End />
        </Series.Sequence>
      </Series>
      <Audio src={staticFile("track.wav")} />
    </>
  );
};

export const MyComposition = () => {
  return (
    <Composition id="Launch" component={Launch} durationInFrames={1500} fps={30} width={1920} height={1080} />
  );
};
