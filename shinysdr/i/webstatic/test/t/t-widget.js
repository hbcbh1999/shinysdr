// Copyright 2014, 2016 Kevin Reid <kpreid@switchb.org>
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

define(['events', 'types', 'values', 'widget', 'widgets/basic'],
       ( events,   types,   values,   widget,   widgets_basic) => {
  'use strict';
  
  const Block = widgets_basic.Block;
  const Scheduler = events.Scheduler;
  
  describe('widget', function () {
    let context;
    let scheduler;
    beforeEach(function () {
      scheduler = new Scheduler(window);
      context = new widget.Context({
        widgets: {},
        scheduler: scheduler
      });
    });
  
    describe('createWidget', function () {
      it('should handle a broken widget', function() {
        function TestWidget(config) {
          throw new Error('Widget construction error for testing.');
        }
      
        const container = document.createElement('div');
        document.body.appendChild(container);
        const wEl = container.appendChild(document.createElement('div'));
        const cell = new values.LocalCell(Number, 0);
        const widgetHandle = widget.createWidgetExt(context, TestWidget, wEl, cell);
        // implicitly expect not to throw
        expect(container.firstChild.className).toBe('widget-ErrorWidget');
      });

      it('should call lifecycle callbacks', function() {
        let calledInit = 0;
        let calledDestroy = 0;
        let poked = 0;
        let poke;
      
        function OuterWidget(config) {
          widgets_basic.Block.call(this, config, function (block, addWidget, ignore, setInsertion, setToDetails, getAppend) {
            addWidget('inner', TestWidget);
          });
        }
        function TestWidget(config) {
          console.log('TestWidget instantiated');
          this.element = config.element;
          widget.addLifecycleListener(this.element, 'init', function() {
            calledInit++;
          });
          widget.addLifecycleListener(this.element, 'destroy', function() {
            calledDestroy++;
          });
          poke = config.boundedFn(function() {
            poked++;
          });
        }
      
        const container = document.createElement('div');
        document.body.appendChild(container);
        const wEl = container.appendChild(document.createElement('div'));
        const cell = new values.LocalCell(types.block, values.makeBlock({
          inner: new values.LocalCell(Number, 0)
        }));
        const widgetHandle = widget.createWidgetExt(context, OuterWidget, wEl, cell);
        expect(calledInit).toBe(1);
        expect(calledDestroy).toBe(0);
        expect(poked).toBe(0);
        poke();
        expect(poked).toBe(1);
        widgetHandle.destroy();
        expect(calledInit).toBe(1);
        expect(calledDestroy).toBe(1);
        poke();
        expect(poked).toBe(1);
      });
    });
  });
  
  return 'ok';
});