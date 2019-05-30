//define new odoo js model
odoo.define('map_view.AssetMapView', function (require) {
"use strict";
//import models

var AbstractController = require('web.AbstractController');
var AbstractModel = require('web.AbstractModel');
var AbstractRenderer = require('web.AbstractRenderer');
var AbstractView = require('web.AbstractView');
var viewRegistry = require('web.view_registry');


var AssetMapController = AbstractController.extend({});
var AssetMapRenderer = AbstractRenderer.extend({
    className :"o_map_style",
//render the map when the view is attach
      on_attach_callback: function () {
       this.isInDOM = true;
        this._render_map();
    },

    //call every time the view is rendered
    _render : function(){
    //view is attach to DOM so we render the map from render not from on_attach_callback
            if (this.isInDOM){
                this._render_map();
                return $.when();
            }
           	this.$el.append(
                $('<div id ="maps"/>'),
             );
        return $.when();
    },

//create map
    _render_map : function () {
    // if leaflet has already render the map we call _render_markers()
         if (!this.map) {
            this.map = L.map('maps').setView([33.5138, 36.2765], 12);
             L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                attribution: '© <a href="http://www.openstreetmap.org/copyright">OpenStreetMap</a>',
                maxZoom: 19,
            }).addTo(this.map);
        }
        // create markers after calling map
        this._render_markers();
    },

     _render_markers: function () {
        var self = this;

        if (this.markers) this.markers.map(function (marker) {marker.removeFrom(self.map);});
        this.markers = [];
        var markerCluster = L.markerClusterGroup();

// the state has info from the model
        this.state.locations.forEach(function (location) {
            self.markers.push(markerCluster.addLayer( L.marker(
                    [location.lat, location.lang],
                    {title:"asset " +location.name +" in "+location.location_name , book_assets_id: location.book_assets_id}
               )
                .bindPopup("asset " +location.name +" in "+location.location_name).openPopup()
                .on('click',self._onLocationMarkerClick.bind(self))
               ));

        });
        self.map.addLayer(markerCluster);

    },


    _onLocationMarkerClick: function (event) {
        var action = {
            type: 'ir.actions.act_window',
            views: [[false, 'form']],
            res_model: 'asset_management.book_assets',
            res_id: event.target.options.book_assets_id,
        };
        this.do_action(action);
    }

});


var AssetMapModel = AbstractModel.extend({

    //send fetched data to renderer
    get : function(){
        return { locations : this.locations,
        };
    },

    //to fetch data from server
    //when the view is for the first time the load method is called


    load :function(params){
        this.displayAssetLocation = params.displayAssetLocation ? true : false ;
        return this._load(params)
        },
// for search view
    reload: function (id, params) {
        return this._load(params);
    },

    _load : function (params){
    // domain change to determine new set of data
        this.domain = params.domain || this.domain || [];

        if (this.displayAssetLocation){
            var self = this;
            //get data from server
            return this._rpc ({
                model:'asset_management.asset',
                method :'get_coordination',
                args:[this.domain]
            })
            //but fetched data in var
            .then(function (result) {
                self.locations = result;
            });
            this.locations = [];
            return $.when();
        }
    },


});

// define view structure
var AssetMapView = AbstractView.extend({
    config: {
        Model: AssetMapModel,
        Controller: AssetMapController,
        Renderer: AssetMapRenderer,
    },

    cssLibs: [
            '/map_view/static/lib/leaflet/leaflet.css',
            '/map_view/static/lib/Leaflet.markercluster-1.4.1/dist/MarkerCluster.css',
            '/map_view/static/lib/Leaflet.markercluster-1.4.1/dist/MarkerCluster.Default.css'
            ],
    jsLibs: [
            '/map_view/static/lib/leaflet/leaflet-src.js',
            '/map_view/static/lib/Leaflet.markercluster-1.4.1/dist/leaflet.markercluster.js'],

    viewType: 'map_view',
    groupable: false,

     init: function () {
        this._super.apply(this, arguments);
        this.loadParams.displayAssetLocation = this.arch.attrs.display_asset_location;
    },

});

//export view
viewRegistry.add('map_view', AssetMapView);

return AssetMapViews;

});
