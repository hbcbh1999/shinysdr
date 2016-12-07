// Copyright 2014, 2015, 2016 Kevin Reid <kpreid@switchb.org>
// 
// This file is part of ShinySDR.
// 
// ShinySDR is free software: you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.
// 
// ShinySDR is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
// GNU General Public License for more details.
// 
// You should have received a copy of the GNU General Public License
// along with ShinySDR.  If not, see <http://www.gnu.org/licenses/>.

require.config({
  baseUrl: '/client/'
});
define(['audio', 'coordination', 'events', 'types', 'values', 'widget', 'widgets'],
       ( audio,   coordination,   events,   types,   values,   widget,   widgets ) => {
  'use strict';
  
  const scheduler = new events.Scheduler();
  const audioContext = new AudioContext();
  
  const adapter = new audio.AudioAnalyserAdapter(scheduler, audioContext);
  adapter.paused.set(false);
  
  navigator.mediaDevices.getUserMedia({audio: true}).then(function getUserMediaSuccess(stream) {
    const source = audioContext.createMediaStreamSource(stream);
    adapter.connectFrom(source);
  }, function getUserMediaFailure(e) {
    const d = document.createElement('dialog');
    // e is a DOMException
    d.textContent = 'Failed to get audio input: ' + e.name;
    document.body.appendChild(d);
    d.show();
  });
  
  const root = new values.ConstantCell(types.block, adapter);
  
  const context = new widget.Context({
    widgets: widgets,
    // Using sessionStorage because we want default settings and because our storage usage doesn't yet distinguish between different pages.
    clientState: new coordination.ClientStateObject(sessionStorage, null),
    scheduler: scheduler
  });
  
  widget.createWidgets(root, context, document);
});
