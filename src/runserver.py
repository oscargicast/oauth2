import httplib2
import json
import random
import requests
import string

from flask import Flask, render_template, request, redirect, url_for
from flask import jsonify, flash, make_response
from flask import session as login_session

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database_setup import Restaurant, MenuItem

from oauth2client.client import flow_from_clientsecrets
from oauth2client.client import FlowExchangeError


app = Flask(__name__)

CLIENT_ID = json.loads(
    open('client_secrets.json', 'r').read()
)['web']['client_id']
APPLICATION_NAME = "Restaurant Menu Application"

engine = create_engine('sqlite:///restaurantmenu.db')
DBSession = sessionmaker(bind=engine)
session = DBSession()


# Create a state token to prevent request forgery.
# Store it in the session for later validation.
@app.route('/login/')
def ShowLogin():
    state = ''.join(random.choice(string.ascii_uppercase + string.digits)
                    for x in xrange(32))
    login_session['state'] = state
    return render_template(
        'login.html',
        STATE=state,
        CLIENT_ID=CLIENT_ID,
    )


@app.route('/gconnect', methods=['POST'])
def gconnect():
    # Validate state token.
    if request.args.get('state') != login_session['state']:
        response = make_response(json.dumps('Invalid state parameter.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Obtain authorization code.
    code = request.data

    try:
        # Upgrade the authorization code into a credentials object.
        oauth_flow = flow_from_clientsecrets('client_secrets.json', scope='')
        oauth_flow.redirect_uri = 'postmessage'
        credentials = oauth_flow.step2_exchange(code)
    except FlowExchangeError:
        response = make_response(
            json.dumps('Failed to upgrade the authorization code.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Check that the access token is valid.
    access_token = credentials.access_token
    url = ('https://www.googleapis.com/oauth2/v1/tokeninfo?access_token=%s'
           % access_token)
    h = httplib2.Http()
    result = json.loads(h.request(url, 'GET')[1])
    # If there was an error in the access token info, abort.
    if result.get('error') is not None:
        response = make_response(json.dumps(result.get('error')), 500)
        response.headers['Content-Type'] = 'application/json'

    # Verify that the access token is used for the intended user.
    gplus_id = credentials.id_token['sub']
    if result['user_id'] != gplus_id:
        response = make_response(
            json.dumps("Token's user ID doesn't match given user ID."), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Verify that the access token is valid for this app.
    if result['issued_to'] != CLIENT_ID:
        response = make_response(
            json.dumps("Token's client ID does not match app's."), 401)
        print "Token's client ID does not match app's."
        response.headers['Content-Type'] = 'application/json'
        return response

    # Check to see if user is already logged in.
    stored_credentials = login_session.get('credentials')
    stored_gplus_id = login_session.get('gplus_id')
    if stored_credentials is not None and gplus_id == stored_gplus_id:
        response = make_response(
            json.dumps('Current user is already connected.'),
            200,
        )
        response.headers['Content-Type'] = 'application/json'
        return response

    # Store the access token in the session for later use.
    login_session['credentials'] = credentials.access_token
    login_session['gplus_id'] = gplus_id

    # Get user info
    userinfo_url = "https://www.googleapis.com/oauth2/v1/userinfo"
    params = {'access_token': credentials.access_token, 'alt': 'json'}
    answer = requests.get(userinfo_url, params=params)

    data = answer.json()

    login_session['username'] = data['name']
    login_session['picture'] = data['picture']
    login_session['email'] = data['email']

    output = ''
    output += '<h1>Welcome, '
    output += login_session['username']
    output += '!</h1>'
    output += '<img src="'
    output += login_session['picture']
    output += ' " style = "width: 300px; height: 300px;border-radius: 150px;-webkit-border-radius: 150px;-moz-border-radius: 150px;"> '
    flash("you are now logged in as %s" % login_session['username'])
    print "done!"
    return output


@app.route('/logout/')
@app.route('/gdisconnect/')
def gdisconnect():
    # Only disconnect a connected user.
    credentials = login_session.get('credentials')
    if credentials is None:
        response = make_response(
            json.dumps('Current user not connected.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response
    access_token = credentials
    url = 'https://accounts.google.com/o/oauth2/revoke?token=%s' % access_token
    h = httplib2.Http()
    result = h.request(url, 'GET')[0]

    if result['status'] == '200':
        # Reset the user's sesson.
        del login_session['credentials']
        del login_session['gplus_id']
        del login_session['username']
        del login_session['email']
        del login_session['picture']

        response = make_response(json.dumps('Successfully disconnected.'), 200)
        response.headers['Content-Type'] = 'application/json'
        return response
    else:
        # For whatever reason, the given token was invalid.
        response = make_response(
            json.dumps('Failed to revoke token for given user.', 400))
        response.headers['Content-Type'] = 'application/json'
        return response

# JSON APIs to view Restaurant Information.


@app.route('/restaurants/<int:restaurant_id>/menu/JSON/')
def ShowMenuJSON(restaurant_id):
    restaurant = session.query(Restaurant).filter_by(id=restaurant_id).one()
    items = session.query(MenuItem).filter_by(
        restaurant_id=restaurant.id,
    ).all()
    return jsonify(MenuItems=[i.serialize for i in items])


@app.route('/restaurants/<int:restaurant_id>/<int:menu_id>/JSON/')
def MenuItemJSON(restaurant_id, menu_id):
    item = session.query(MenuItem).filter_by(
        restaurant_id=restaurant_id,
        id=menu_id,
    ).one()
    return jsonify(MenuItems=item.serialize)


@app.route('/restaurant/JSON')
def RestaurantsJSON():
    restaurants = session.query(Restaurant).all()
    return jsonify(restaurants=[r.serialize for r in restaurants])


# Show all restaurants.
@app.route('/')
@app.route('/restaurants/')
def ShowRestaurants():
    restaurants = session.query(Restaurant).all()
    return render_template(
        'restaurants.html',
        restaurants=restaurants,
    )


# Create a new restaurant.
@app.route('/restaurant/new/', methods=['GET', 'POST'])
def NewRestaurant():
    if 'username' not in login_session:
        return redirect('/login')
    if request.method == 'POST':
        new_restaurant = Restaurant(name=request.form['name'])
        session.add(new_restaurant)
        flash('New Restaurant %s Successfully Created' % new_restaurant.name)
        session.commit()
        return redirect(url_for('ShowRestaurants'))
    else:
        return render_template('new-restaurant.html')


# Edit a restaurant.
@app.route('/restaurant/<int:restaurant_id>/edit/', methods=['GET', 'POST'])
def EditRestaurant(restaurant_id):
    edited_restaurant = session.query(
        Restaurant).filter_by(id=restaurant_id).one()
    if request.method == 'POST':
        if request.form['name']:
            edited_restaurant.name = request.form['name']
            flash('Restaurant Successfully Edited %s' % edited_restaurant.name)
            return redirect(url_for('ShowRestaurants'))
    else:
        return render_template(
            'edit-restaurant.html',
            restaurant=edited_restaurant,
        )


# Delete a restaurant.
@app.route('/restaurant/<int:restaurant_id>/delete/', methods=['GET', 'POST'])
def DeleteRestaurant(restaurant_id):
    restaurant_to_delete = session.query(
        Restaurant).filter_by(id=restaurant_id).one()
    if request.method == 'POST':
        session.delete(restaurant_to_delete)
        flash('%s Successfully Deleted' % restaurant_to_delete.name)
        session.commit()
        return redirect(url_for(
            'ShowRestaurants',
            restaurant_id=restaurant_id,
        ))
    else:
        return render_template(
            'delete-restaurant.html',
            restaurant=restaurant_to_delete,
        )


# Show a restaurant menu.
@app.route('/restaurants/<int:restaurant_id>/')
@app.route('/restaurant/<int:restaurant_id>/menu/')
def ShowMenu(restaurant_id):
    restaurant = session.query(Restaurant).filter_by(id=restaurant_id).one()
    items = session.query(MenuItem).filter_by(restaurant_id=restaurant.id)
    return render_template(
        'menu.html',
        restaurant=restaurant,
        items=items,
    )


# Create a new menu item.
@app.route('/restaurant/<int:restaurant_id>/new/', methods=['GET', 'POST'])
def NewMenuItem(restaurant_id):
    if request.method == 'POST':
        new_item = MenuItem(
            name=request.form.get('name'),
            description=request.form.get('description'),
            price=request.form.get('price'),
            course=request.form.get('course'),
            restaurant_id=restaurant_id,
        )
        session.add(new_item)
        session.commit()
        flash("new menu item created!")
        return redirect(url_for(
            'ShowMenu',
            restaurant_id=restaurant_id,
        ))
    else:
        return render_template(
            'new-menu-item.html',
            restaurant_id=restaurant_id,
        )


# Edit a menu item.
@app.route('/restaurant/<int:restaurant_id>/<int:menu_id>/edit/',
           methods=['GET', 'POST'])
def EditMenuItem(restaurant_id, menu_id):
    edited_item = session.query(MenuItem).filter_by(id=menu_id).one()
    if request.method == 'POST':
        edited_item.name = request.form.get('name')
        edited_item.description = request.form.get('description')
        edited_item.price = request.form.get('price')
        edited_item.course = request.form.get('course')
        session.add(edited_item)
        session.commit()
        flash("menu item edited!")
        return redirect(url_for(
            'ShowMenu',
            restaurant_id=restaurant_id,
        ))
    else:
        return render_template(
            'edit-menu-item.html',
            item=edited_item,
        )


# Delete a menu item.
@app.route('/restaurant/<int:restaurant_id>/<int:menu_id>/delete/',
           methods=['GET', 'POST'])
def DeleteMenuItem(restaurant_id, menu_id):
    item = session.query(MenuItem).filter_by(id=menu_id).one()
    if request.method == 'POST':
        session.delete(item)
        session.commit()
        flash("menu item deleted!")
        return redirect(url_for(
            'ShowMenu',
            restaurant_id=restaurant_id,
        ))
    else:
        return render_template(
            'delete-menu-item.html',
            item=item,
        )


if __name__ == '__main__':
    app.secret_key = 'super_secret_key'
    app.debug = True
    app.run(host='0.0.0.0', port=8000)
